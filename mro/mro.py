﻿# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo
#    Copyright (C) 2013-2016 CodUP (<http://codup.com>).
#
##############################################################################

from openerp import api, fields, models, _
from openerp import netsvc
from openerp.exceptions import Warning
import openerp.addons.decimal_precision as dp
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT as OE_DTFORMAT

from datetime import datetime, timedelta


class mro_order(models.Model):
    """
    Maintenance Orders
    """
    _name = 'mro.order'
    _description = 'Maintenance Order'
    _inherit = ['mail.thread', 'ir.needaction_mixin']

    STATE_SELECTION = [
        ('draft', 'Draft'),
        ('assigned', 'Assigned'),
        ('released', 'Awaiting Parts'),
        ('open', 'Ready'),
        ('done', 'Done'),
        ('cancel', 'Cancelled')
    ]

    MAINTENANCE_TYPE_SELECTION = [
        ('bm', 'Breakdown'),
        ('cm', 'Corrective')
    ]

    @api.multi
    def _track_subtype(self, init_values):
        self.ensure_one()
        if 'state' in init_values and self.state == 'open':
            return 'mro.mt_order_confirmed'
        return super(mro_order, self)._track_subtype(init_values)

    def _get_available_parts(self):
        for order in self:
            line_ids = []
            available_line_ids = []
            done_line_ids = []
            if order.procurement_group_id:
                for procurement in order.procurement_group_id.procurement_ids:
                    line_ids += [move.id for move in procurement.move_ids if move.location_dest_id.id == order.asset_id.property_stock_asset.id]
                    available_line_ids += [move.id for move in procurement.move_ids if move.location_dest_id.id == order.asset_id.property_stock_asset.id and move.state == 'assigned']
                    done_line_ids += [move.id for move in procurement.move_ids if move.location_dest_id.id == order.asset_id.property_stock_asset.id and move.state == 'done']
            order.parts_ready_lines = line_ids
            order.parts_move_lines = available_line_ids
            order.parts_moved_lines = done_line_ids

    @api.multi
    def _get_planned_date(self):
        dt = datetime.now() + timedelta(hours=1)
        if dt.minute % 15 or dt.second:
            dt = dt + timedelta(minutes=15-dt.minute % 15,
                                       seconds=-(dt.second % 60))
        return dt.strftime(OE_DTFORMAT)

    name = fields.Char('Reference', size=64)
    origin = fields.Char('Source Document', size=64, readonly=True, states={'draft': [('readonly', False)]},
        help="Reference of the document that generated this maintenance order.")
    state = fields.Selection(STATE_SELECTION, 'Status', readonly=True,
        help="When the maintenance order is created the status is set to 'Draft'.\n\
        If the order is confirmed the status is set to 'Waiting Parts'.\n\
        If the stock is available then the status is set to 'Ready to Maintenance'.\n\
        When the maintenance is over, the status is set to 'Done'.", default='draft')
    maintenance_type = fields.Selection(MAINTENANCE_TYPE_SELECTION, 'Maintenance Type', required=True, readonly=True, states={'draft': [('readonly', False)]}, default='bm')
    task_id = fields.Many2one('mro.task', 'Task', readonly=True, states={'draft': [('readonly', False)]})
    description = fields.Char('Description', size=64, translate=True, required=True, readonly=True, states={'draft': [('readonly', False)]})
    asset_id = fields.Many2one('asset.asset', 'Asset', required=True, readonly=True, states={'draft': [('readonly', False)]})
    date_planned = fields.Datetime('Planned Date', required=True, select=1, readonly=True, states={'draft':[('readonly',False)]}, default=_get_planned_date)
    date_scheduled = fields.Datetime('Scheduled Date', required=True, select=1, readonly=True, states={'draft':[('readonly',False)],'released':[('readonly',False)],'open':[('readonly',False)]})
    date_execution = fields.Datetime('Execution Date', required=True, states={'done':[('readonly',True)],'cancel':[('readonly',True)]})
    parts_lines = fields.One2many('mro.order.parts.line', 'maintenance_id', 'Planned parts')
    parts_ready_lines = fields.One2many('stock.move', compute='_get_available_parts')
    parts_move_lines = fields.One2many('stock.move', compute='_get_available_parts')
    parts_moved_lines = fields.One2many('stock.move', compute='_get_available_parts')
    tools_description = fields.Text('Tools Description',translate=True)
    labor_description = fields.Text('Labor Description',translate=True)
    operations_description = fields.Text('Operations Description',translate=True)
    documentation_description = fields.Text('Documentation Description',translate=True)
    problem_description = fields.Text('Problem Description')
    company_id = fields.Many2one('res.company','Company',required=True, readonly=True, states={'draft':[('readonly',False)]}, default=lambda self: self.env['res.company']._company_default_get('mro.order'))
    procurement_group_id = fields.Many2one('procurement.group', 'Procurement group', copy=False)
    category_ids = fields.Many2many(related='asset_id.category_ids', string='Asset Category', readonly=True)

    _order = 'date_execution'

    @api.onchange('asset_id')
    def onchange_asset(self):
        if self.asset_id:
            self.category_ids = self.asset_id.category_ids

    @api.onchange('date_planned')
    def onchange_planned_date(self):
        self.date_scheduled = self.date_planned

    @api.onchange('date_scheduled')
    def onchange_scheduled_date(self):
        self.date_execution = self.date_scheduled

    @api.onchange('date_execution')
    def onchange_execution_date(self):
        if self.state == 'draft':
            self.date_planned = self.date_execution
        else:
            self.date_scheduled = self.date_execution

    @api.onchange('task_id')
    def onchange_task(self):
        task = self.task_id
        new_parts_lines = []
        for line in task.parts_lines:
            new_parts_lines.append([0,0,{
                'name': line.name,
                'parts_id': line.parts_id.id,
                'parts_qty': line.parts_qty,
                'parts_uom': line.parts_uom.id,
                }])
        self.parts_lines = new_parts_lines
        self.description = task.name
        self.tools_description = task.tools_description
        self.labor_description = task.labor_description
        self.operations_description = task.operations_description
        self.documentation_description = task.documentation_description

    def test_ready(self):
        res = True
        for order in self:
            if order.parts_lines and order.procurement_group_id:
                states = []
                for procurement in order.procurement_group_id.procurement_ids:
                    states += [move.state != 'assigned' for move in procurement.move_ids if move.location_dest_id.id == order.asset_id.property_stock_asset.id]
                if any(states) or len(states) == 0: res = False
        return res

    def procure_parts(self, group_id=False):
        procurement_obj = self.env['procurement.order']
        proc_ids = []
        group_id = group_id or \
                self.env['procurement.group'].create({
                    'name': self.name,
                    })
        for line in self.parts_lines:
            if line.procurement_id:
                continue
            vals = {
                'name': self.name,
                'origin': self.name,
                'company_id': self.company_id.id,
                'group_id': group_id.id,
                'date_planned': self.date_planned,
                'product_id': line.parts_id.id,
                'product_qty': line.parts_qty,
                'product_uom': line.parts_uom.id,
                'location_id': self.asset_id.property_stock_asset.id
                }
            proc_id = procurement_obj.create(vals)
            proc_ids.append(proc_id)
            line.write({'procurement_id': proc_id.id})
        procurement_obj.run(proc_ids)
        return group_id

    @api.multi
    def action_procure(self):
        for order in self:
            procurement_group_id = self.procure_parts(
                    group_id=order.procurement_group_id or False)
            if not order.procurement_group_id:
                order.write({
                    'procurement_group_id': procurement_group_id.id,
                    })
        return True

    def action_confirm(self):
        for order in self:
            order.action_procure()
            order.write({ 'state': 'released'})
        return 0

    @api.multi
    def button_assign(self):
        if not self.user_id:
            raise Warning(_("You must add an assigned user"))
        self.write({'state': 'assigned'})
        return True

    def action_ready(self):
        self.write({'state': 'open'})
        return True

    def action_done(self):
        for order in self:
            order.action_procure()
            if not order.parts_move_lines:
                continue
            order.parts_move_lines.action_done()
        self.write({'state': 'done', 'date_execution': fields.Datetime.now()})
        return True

    def action_cancel(self):
        for order in self:
            order.parts_ready_lines.action_cancel()
        self.write({'state': 'cancel'})
        return True

    def test_if_parts(self):
        res = True
        for order in self:
            if not order.parts_lines:
                res = False
        return res

    @api.multi
    def force_done(self):
        self.force_parts_reservation()
        wf_service = netsvc.LocalService("workflow")
        for order in self:
            wf_service.trg_validate(self.env.user.id, 'mro.order', order.id, 'button_done', self.env.cr)
        return True

    @api.multi
    def force_parts_reservation(self):
        for order in self:
            order.parts_ready_lines.force_assign()
        return True

    @api.model
    def create(self, vals):
        if vals.get('name','/')=='/':
            vals['name'] = self.env['ir.sequence'].get('mro.order') or '/'
        return super(mro_order, self).create(vals)

    @api.multi
    def write(self, vals):
        if vals.get('date_execution') and not vals.get('state'):
            # constraint for calendar view
            for order in self:
                if order.state == 'draft':
                    vals['date_planned'] = vals['date_execution']
                    vals['date_scheduled'] = vals['date_execution']
                elif order.state in ('released','open'):
                    vals['date_scheduled'] = vals['date_execution']
                else: del vals['date_execution']
        return super(mro_order, self).write(vals)


class mro_order_parts_line(models.Model):
    _name = 'mro.order.parts.line'
    _description = 'Maintenance Planned Parts'

    name = fields.Char('Description', size=64)
    parts_id = fields.Many2one('product.product', 'Parts', required=True)
    parts_qty = fields.Float('Quantity',
            digits_compute=dp.get_precision('Product Unit of Measure'),
            required=True, default=1.0)
    parts_uom = fields.Many2one('product.uom', 'Unit of Measure',required=True)
    maintenance_id = fields.Many2one('mro.order', 'Maintenance Order',
            select=True)
    procurement_id = fields.Many2one('procurement.order', 'Procurement Order',
            select=True)
    state = fields.Selection(related='procurement_id.state')

    @api.onchange('parts_id')
    def onchange_parts(self):
        self.parts_uom = self.parts_id.uom_id

    def unlink(self):
        self.write({'maintenance_id': False})
        return True

    @api.model
    def create(self, values):
        ids = self.search([('maintenance_id','=',values['maintenance_id']),('parts_id','=',values['parts_id'])])
        if len(ids)>0:
            values['parts_qty'] = ids[0].parts_qty + values['parts_qty']
            ids[0].write(values)
            return ids[0]
        ids = self.search([('maintenance_id','=',False)])
        if len(ids)>0:
            ids[0].write(values)
            return ids[0]
        return super(mro_order_parts_line, self).create(values)


class mro_task(models.Model):
    """
    Maintenance Tasks (Template for order)
    """
    _name = 'mro.task'
    _description = 'Maintenance Task'

    MAINTENANCE_TYPE_SELECTION = [
        ('cm', 'Corrective')
    ]

    name = fields.Char('Description', size=64, required=True, translate=True)
    category_id = fields.Many2one('asset.category', 'Asset Category', ondelete='restrict', required=True)
    maintenance_type = fields.Selection(MAINTENANCE_TYPE_SELECTION, 'Maintenance Type', required=True, default='cm')
    parts_lines = fields.One2many('mro.task.parts.line', 'task_id', 'Parts')
    tools_description = fields.Text('Tools Description',translate=True)
    labor_description = fields.Text('Labor Description',translate=True)
    operations_description = fields.Text('Operations Description',translate=True)
    documentation_description = fields.Text('Documentation Description',translate=True)
    active = fields.Boolean('Active', default=True)


class mro_task_parts_line(models.Model):
    _name = 'mro.task.parts.line'
    _description = 'Maintenance Planned Parts'

    name = fields.Char('Description', size=64)
    parts_id = fields.Many2one('product.product', 'Parts', required=True)
    parts_qty = fields.Float('Quantity', digits_compute=dp.get_precision('Product Unit of Measure'), required=True, default=1.0)
    parts_uom = fields.Many2one('product.uom', 'Unit of Measure', required=True)
    task_id = fields.Many2one('mro.task', 'Maintenance Task', select=True)

    @api.onchange('parts_id')
    def onchange_parts(self):
        self.parts_uom = self.parts_id.uom_id.id

    def unlink(self):
        self.write({'task_id': False})
        return True

    @api.model
    def create(self, values):
        ids = self.search([('task_id','=',values['task_id']),('parts_id','=',values['parts_id'])])
        if len(ids)>0:
            values['parts_qty'] = ids[0].parts_qty + values['parts_qty']
            ids[0].write(values)
            return ids[0]
        ids = self.search([('task_id','=',False)])
        if len(ids)>0:
            ids[0].write(values)
            return ids[0]
        return super(mro_task_parts_line, self).create(values)


class mro_request(models.Model):
    _name = 'mro.request'
    _description = 'Maintenance Request'
    _inherit = ['mail.thread', 'ir.needaction_mixin']

    STATE_SELECTION = [
        ('draft', 'Draft'),
        ('claim', 'Claim'),
        ('run', 'Execution'),
        ('done', 'Done'),
        ('reject', 'Rejected'),
        ('cancel', 'Canceled')
    ]

    @api.multi
    def _track_subtype(self, init_values):
        self.ensure_one()
        if 'state' in init_values and self.state == 'claim':
            return 'mro.mt_request_sent'
        elif 'state' in init_values and self.state == 'run':
            return 'mro.mt_request_confirmed'
        elif 'state' in init_values and self.state == 'reject':
            return 'mro.mt_request_rejected'
        return super(mro_request, self)._track_subtype(init_values)

    @api.multi
    def _get_planned_date(self):
        dt = datetime.now() + timedelta(hours=1)
        if dt.minute % 15 or dt.second:
            dt = dt + timedelta(minutes=15-dt.minute % 15,
                                       seconds=-(dt.second % 60))
        return dt.strftime(OE_DTFORMAT)

    name = fields.Char('Reference', size=64)
    state = fields.Selection(STATE_SELECTION, 'Status', readonly=True,
        help="When the maintenance request is created the status is set to 'Draft'.\n\
        If the request is sent the status is set to 'Claim'.\n\
        If the request is confirmed the status is set to 'Execution'.\n\
        If the request is rejected the status is set to 'Rejected'.\n\
        When the maintenance is over, the status is set to 'Done'.", track_visibility='onchange', default='draft')
    asset_id = fields.Many2one('asset.asset', 'Asset', required=True, readonly=True, states={'draft': [('readonly', False)]})
    cause = fields.Char('Cause', size=64, translate=True, required=True, readonly=True, states={'draft': [('readonly', False)]})
    description = fields.Text('Description', readonly=True, states={'draft': [('readonly', False)]})
    reject_reason = fields.Text('Reject Reason', readonly=True)
    requested_date = fields.Datetime('Requested Date', required=True, select=1, readonly=True, states={'draft': [('readonly', False)]}, help="Date requested by the customer for maintenance.", default=_get_planned_date)
    execution_date = fields.Datetime('Execution Date', required=True, select=1, readonly=True, states={'draft':[('readonly',False)],'claim':[('readonly',False)]},default=_get_planned_date)
    breakdown = fields.Boolean('Breakdown', readonly=True, states={'draft': [('readonly', False)]}, default=False)
    create_uid = fields.Many2one('res.users', 'Responsible')

    @api.onchange('requested_date')
    def onchange_requested_date(self):
        self.execution_date = self.requested_date

    @api.onchange('execution_date','state','breakdown')
    def onchange_execution_date(self):
        if self.state == 'draft' and not self.breakdown:
            self.requested_date = self.execution_date

    def action_send(self):
        value = {'state': 'claim'}
        for request in self:
            if request.breakdown:
                value['requested_date'] = fields.Datetime.now()
            request.write(value)

    def action_confirm(self):
        order = self.env['mro.order']
        order_id = False
        for request in self:
            order_id = order.create({
                'date_planned':request.requested_date,
                'date_scheduled':request.requested_date,
                'date_execution':request.requested_date,
                'origin': request.name,
                'state': 'draft',
                'maintenance_type': 'bm',
                'asset_id': request.asset_id.id,
                'description': request.cause,
                'problem_description': request.description,
            })
        self.write({'state': 'run'})
        return order_id.id

    def action_done(self):
        self.write({'state': 'done', 'execution_date': fields.Datetime.now()})
        return True

    def action_reject(self):
        self.write({'state': 'reject', 'execution_date': fields.Datetime.now()})
        return True

    def action_cancel(self):
        self.write({'state': 'cancel', 'execution_date': fields.Datetime.now()})
        return True

    @api.model
    def create(self, vals):
        if vals.get('name','/')=='/':
            vals['name'] = self.env['ir.sequence'].get('mro.request') or '/'
        return super(mro_request, self).create(vals)

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
