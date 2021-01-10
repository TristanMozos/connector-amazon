# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import datetime
from datetime import datetime, timedelta

from odoo import fields, models, api, _
from odoo.exceptions import UserError

class WizardDeleteAmazonProduct(models.TransientModel):
    _name = "amazon.delete.product.wizard"
    _description = "Delete Amazon Product Wizard"

    @api.multi
    def name_get(self):
        result = []
        for wizard in self:
            name = 'Wizard to delete Amazon product'
            result.append((wizard.id, name))
        return result

    @api.multi
    def delete_from_amazon_product(self):
        if self._context.get('active_ids', []):
            if self:
                wizard = self

            amz_products = self.env['amazon.product.product'].browse(self._context.get('active_ids', []))
            list_products = []
            for amz_product in amz_products:
                list_products.append(amz_product)

            if list_products:
                return self.delete_amazon_product(product_list=list_products)

    @api.multi
    def delete_from_product_template(self):
        if self._context.get('active_ids', []):
            if self:
                wizard = self

            products = self.env['product.template'].browse(self._context.get('active_ids', []))
            list_products = []
            for product in products:
                if product.product_variant_id.amazon_bind_ids:
                    for amz_product in product.product_variant_id.amazon_bind_ids:
                        list_products.append(amz_product)

            if list_products:
                return self.delete_amazon_product(product_list=list_products)

    @api.multi
    def delete_amazon_product(self, product_list):
        if not product_list:
            raise UserError(_('You must select one or more products to delete'))

        for amz_prod in product_list:
            data = {'backend_id': amz_prod.backend_id.id,
                    'marketplace_ids': amz_prod.backend_id.marketplace_ids.mapped('id'),
                    'amazon_product_id': amz_prod.id,
                    }

            vals = {'backend_id': amz_prod.backend_id.id,
                    'type': '_POST_PRODUCT_DATA_DELETE_',
                    'model': self._name,
                    'identificator': self.id,
                    'data': data,
                    }
            self.env['amazon.feed.tothrow'].create(vals)

        return




