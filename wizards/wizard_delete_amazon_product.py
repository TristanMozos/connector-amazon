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

    def name_get(self):
        result = []
        for wizard in self:
            name = 'Wizard to delete Amazon product'
            result.append((wizard.id, name))
        return result

    def delete_amazon_product(self):
        if self._context.get('active_ids', []):
            if self:
                wizard = self

            products = self.env['product.template'].browse(self._context.get('active_ids', []))

            if not products:
                raise UserError(_('You must select one or more products to delete'))

            with wizard.backend_id.work_on(self._name) as work:
                importer_product_forid = work.component(model_name='amazon.product.product', usage='amazon.product.data.import')

                for product in products:
                    # if product.is_amazon_product:
                    #    wizard.write({'product_cant_export_ids':[(0, 0, {'product_id':product.id,
                    #                                                     'can_be_export':'no_is_amazon_product'})]})
                    if product.product_variant_id.amazon_bind_ids:
                        wizard.write({'product_export_ids':[(0, 0, {'product_id':product.id,
                                                                    'asin':product.product_variant_id.amazon_bind_ids.asin})]})

                    elif not product.barcode and not product.product_variant_id.barcode:
                        wizard.write({'product_cant_export_ids':[(0, 0, {'product_id':product.id,
                                                                         'can_be_export':'no_hasnt_barcode'})]})
                    elif product.barcode or product.product_variant_id.barcode:
                        has_data = False
                        marketplaces = self.marketplace_ids or backend_id.marketplace_ids
                        for marketplace in marketplaces:
                            amazon_product = importer_product_forid.run_products_for_id(ids=[product.barcode or product.product_variant_id.barcode],
                                                                                        type_id=None,
                                                                                        marketplace_mws=marketplace.id_mws)
                            if amazon_product:
                                wizard.write({'product_export_ids':[(0, 0, {'product_id':product.id,
                                                                            'asin':amazon_product[0]['asin']})]})
                                has_data = True
                                break

                        if not has_data:
                            wizard.write({'product_cant_export_ids':[(0, 0, {'product_id':product.id,
                                                                             'can_be_export':'no_existing_on_amazon'})]})
                    else:
                        wizard.write({'product_cant_export_ids':[(0, 0, {'product_id':product.id,
                                                                         'can_be_export':'no_undefined_reason'})]})

            if not wizard.product_export_ids:
                raise UserError(_('There aren\'t products to export'))

        return


