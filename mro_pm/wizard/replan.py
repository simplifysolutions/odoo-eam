﻿# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo
#    Copyright (C) 2013-2016 CodUP (<http://codup.com>).
#
##############################################################################

from openerp import api, fields, models


class mro_pm_replan(models.TransientModel):
    _name = 'mro.pm.replan'
    _description = 'Replan PM'

    @api.multi
    def replan_pm(self):
        self.env['mro.order'].replan_pm()
        return {'type': 'ir.actions.act_window_close',}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
