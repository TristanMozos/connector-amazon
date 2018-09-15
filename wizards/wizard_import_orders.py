# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from datetime import datetime

from odoo import api, fields, models, exceptions


class WizardImportOrders(models.TransientModel):
    _name = "amazon.order.import.wizard"
    _description = "Amazon Import Orders Wizard"

    @staticmethod
    def _validate_dates(date_from, date_to, generate_report=None):
        if date_from > date_to:
            raise exceptions.except_orm('Error', 'The start date must be lower than the end date')
        diference_bet_dates = datetime.now() - datetime.strptime(date_from, '%Y-%m-%d')
        if generate_report == 'report' and diference_bet_dates.days > 90:
            raise exceptions.except_orm('Error', 'Only can get orders by report method with a max of 90 days old (%s)', diference_bet_dates)
        diference_bet_dates = datetime.strptime(date_to, '%Y-%m-%d') - datetime.strptime(date_from, '%Y-%m-%d')
        if diference_bet_dates.days > 60:
            raise exceptions.except_orm('Error', 'The diference between two dates must be lower than 60 days (%s)', diference_bet_dates)

    @api.multi
    def import_orders(self):
        backend_id = self._context.get('active_ids', [])
        try:
            if backend_id:
                backend = self.env['amazon.backend'].browse(backend_id)
                self._validate_dates(date_from=self.date_init, date_to=self.date_end)
                init_date = datetime.strptime(self.date_init, '%Y-%m-%d')
                finish_date = datetime.strptime(self.date_end, '%Y-%m-%d')
                backend._import_sale_orders(import_start_time=init_date, import_end_time=finish_date, generate_report=self.generate_report == 'report')

        except Exception, e:
            raise e

    date_init = fields.Date('Start date', required=True)
    date_end = fields.Date('End date', required=True)
    generate_report = fields.Selection(selection=[('report', 'Generate report'),
                                                  ('direct', 'Get orders directly'), ], required=True, default='report')
