# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from datetime import datetime

from odoo.addons.component.core import Component

from ...models.config.common import AMAZON_DEFAULT_PERCENTAGE_FEE, AMAZON_DEFAULT_PERCENTAGE_MARGIN


class AmazonBindingProductSupplierInfoListener(Component):
    _name = 'amazon.binding.amazon.product.supplierinfo.listener'
    _inherit = 'base.connector.listener'
    _apply_on = ['product.supplierinfo']

    def on_record_create(self, record, fields=None):
        if record:
            time_now = datetime.now()
            cost = None
            for supllier_prod in record.product_tmpl_id.seller_ids:
                if (not cost or cost > supllier_prod.price) and \
                        (not supllier_prod.date_end or datetime.strptime(supllier_prod.date_end, '%Y-%m-%d') > time_now):
                    cost = supllier_prod.price
                    if supllier_prod.name.automatic_export_products and record.product_id.barcode:
                        for marketplace in supllier_prod.name.backend_id.marketplace_ids:
                            supr = self.env['amazon.feed.tothrow'].search([('backend_id', '=', supllier_prod.name.backend_id.id),
                                                                           ('type', '=', 'Add_products_csv'),
                                                                           ('launched', '=', False),
                                                                           ('model', '=', record.product_id._name),
                                                                           ('identificator', '=', record.product_id.id),
                                                                           ('marketplace_id', '=', marketplace.id)])

                            data = {'sku':record.product_id.default_code or record.product_id.product_variant_id.default_code}
                            data['product-id'] = record.product_id.barcode or record.product_id.product_variant_id.barcode
                            data['product-id-type'] = 'EAN'
                            price = record.product_id.product_variant_id._calc_amazon_price(backend=supllier_prod.name.backend_id,
                                                                                            margin=supllier_prod.name.backend_id.max_margin or AMAZON_DEFAULT_PERCENTAGE_MARGIN,
                                                                                            marketplace=marketplace,
                                                                                            percentage_fee=AMAZON_DEFAULT_PERCENTAGE_FEE)
                            data['price'] = ("%.2f" % price).replace('.', marketplace.decimal_currency_separator) if price else ''
                            data['minimum-seller-allowed-price'] = ''
                            data['maximum-seller-allowed-price'] = ''
                            data['item-condition'] = '11'  # We assume the products are new
                            data['quantity'] = '0'  # The products stocks allways is 0 when we export these
                            data['add-delete'] = 'a'
                            data['will-ship-internationally'] = ''
                            data['expedited-shipping'] = ''
                            data['merchant-shipping-group-name'] = ''
                            handling_time = record.product_id.product_variant_id._compute_amazon_handling_time() or ''
                            data['handling-time'] = str(handling_time) if price else ''
                            data['item_weight'] = ''
                            data['item_weight_unit_of_measure'] = ''
                            data['item_volume'] = ''
                            data['item_volume_unit_of_measure'] = ''
                            data['id_mws'] = marketplace.id_mws
                            vals = {'backend_id':supllier_prod.name.backend_id.id,
                                    'type':'Add_products_csv',
                                    'model':record.product_id._name,
                                    'identificator':record.product_id.id,
                                    'marketplace_id':marketplace.id,
                                    'data':data,
                                    }
                            if supr:
                                supr.write(vals)
                            else:
                                self.env['amazon.feed.tothrow'].create(vals)
