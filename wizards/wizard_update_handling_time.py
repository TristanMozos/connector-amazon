# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from datetime import datetime

from odoo import api, fields, models, exceptions


class WizardUpdateHandlingTime(models.TransientModel):
    _name = "amazon.update.handling.time.wizard"
    _description = "Amazon Update Handling Time Wizard"

    @staticmethod
    def _validate_time_handling(time):
        if time < 0 or time > 30:
            raise exceptions.except_orm('Error', 'The time handling must be higher than 0 and lower than 30 days')

    @api.multi
    def update_time_handling(self):
        products_id = self._context.get('active_ids', [])
        try:
            if products_id:
                self._validate_time_handling(time=self.time_handling)
                amazon_products = self.env['amazon.product.product'].search([('odoo_id','in',products_id)])
                for a_product in amazon_products:
                    for detail in a_product.product_product_market_ids:
                        continue

        except Exception, e:
            raise e

    time_handling = fields.Integer('Days between the order date and the ship date', required=True)
