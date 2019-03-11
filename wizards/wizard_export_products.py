# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from datetime import datetime

from odoo import api, fields, models, exceptions
import re

AMAZON_ORDER_ID_PATTERN = '^([\d]{3}-[\d]{7}-[\d]{7})+$'


class WizardImportOrders(models.TransientModel):
    _name = "amazon.orders.import.wizard"
    _description = "Amazon Import Orders Wizard"

    @staticmethod
    def _validate_dates(date_from, date_to, generate_report=None):
        if date_from > date_to:
            raise exceptions.except_orm('Error', 'The start date must be lower than the end date')
        diference_bet_dates = datetime.strptime(date_to, '%Y-%m-%d') - datetime.strptime(date_from, '%Y-%m-%d')
        if generate_report == 'report' and diference_bet_dates.days > 90:
            raise exceptions.except_orm('Error', 'Only can get orders by report method with a max of 90 days old (%s)' % diference_bet_dates)
        elif generate_report != 'report' and diference_bet_dates.days > 15:
            raise exceptions.except_orm('Error', 'The diference between two dates must be lower than 15 days (%s)' % diference_bet_dates)

    @api.multi
    def import_orders(self):
        backend_id = self._context.get('active_ids', [])
        try:
            if backend_id:
                backend = self.env['amazon.backend'].browse(backend_id)
                self._validate_dates(date_from=self.date_init, date_to=self.date_end, generate_report=self.generate_report)
                init_date = datetime.strptime(self.date_init, '%Y-%m-%d')
                finish_date = datetime.strptime(self.date_end, '%Y-%m-%d')
                backend._import_sale_orders(import_start_time=init_date,
                                            import_end_time=finish_date,
                                            generate_report=self.generate_report == 'report',
                                            update_import_date=False)

        except Exception, e:
            raise e

    @api.multi
    def update_orders(self):
        backend_id = self._context.get('active_ids', [])
        try:
            if backend_id:
                backend = self.env['amazon.backend'].browse(backend_id)
                self._validate_dates(date_from=self.date_init, date_to=self.date_end)
                init_date = datetime.strptime(self.date_init, '%Y-%m-%d')
                finish_date = datetime.strptime(self.date_end, '%Y-%m-%d')
                backend._import_updated_sales(import_start_time=init_date,
                                              import_end_time=finish_date,
                                              update_import_date=False)

        except Exception, e:
            raise e

    date_init = fields.Date('Start date', required=True)
    date_end = fields.Date('End date', required=True)
    generate_report = fields.Selection(selection=[('report', 'Generate report'),
                                                  ('direct', 'Get orders directly'), ], required=True, default='report')


class WizardImportOrder(models.TransientModel):
    _name = "amazon.order.import.wizard"
    _description = "Amazon Import Single Order Wizard"

    @staticmethod
    def _validate_id(id_order):
        if not id_order:
            raise exceptions.except_orm('Error', 'The order id is empty')
        if not re.match(AMAZON_ORDER_ID_PATTERN, id_order):
            raise exceptions.except_orm('Error', 'The order id validation failed %s %s' % AMAZON_ORDER_ID_PATTERN, id_order)

    @api.multi
    def import_order(self):
        backend_id = self._context.get('active_ids', [])
        try:
            if backend_id:
                backend = self.env['amazon.backend'].browse(backend_id)
                self._validate_id(self.id_order)
                sale_binding_model = self.env['amazon.sale.order']
                user = backend.warehouse_id.company_id.user_tech_id
                if not user:
                    user = self.env['res.users'].browse(self.env.uid)
                if user != self.env.user:
                    sale_binding_model = sale_binding_model.sudo(user)
                sale_binding_model.import_record(backend, external_id=self.id_order)

        except Exception, e:
            raise e

    id_order = fields.Char('Order Id', required=True)
