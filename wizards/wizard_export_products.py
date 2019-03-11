# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import datetime
from datetime import datetime, timedelta

from odoo import fields, models, api, _
from odoo.exceptions import UserError

from ..models.config.common import AMAZON_DEFAULT_PERCENTAGE_FEE


class WizardProductToAmazonExport(models.TransientModel):
    _name = "amazon.product.to.export.wizard"
    _description = "Product to export to amazon Wizard"

    product_id = fields.Many2one('product.template')
    asin = fields.Char('ASIN of Amazon')

    list_to_export_id = fields.Many2one('amazon.list.products.export.wizard')

    list_cant_be_exported_id = fields.Many2one('amazon.list.products.export.wizard')

    name = fields.Char('Name', related='product_id.name')
    default_code = fields.Char('Default code', related='product_id.default_code')
    barcode = fields.Char('Barcode', related='product_id.product_variant_id.barcode')
    '''
    weight = fields.Char('Weight', related='product_id.weight')
    qty_available = fields.Char('Qty avaiable', related='product_id.qty_available')
    virtual_available = fields.Char('Virtual avaiable', related='product_id.virtual_available')
    '''

    can_be_export = fields.Selection([('Yes', 'yes'),
                                      ('no_is_amazon_product', 'This product has been exported before'),
                                      ('no_hasnt_barcode', 'This product doesn\'t have barcode'),
                                      ('no_existing_on_amazon', 'The product doesn\'t exist on Amazon'),
                                      ('no_undefined_reason', 'Can\'t be exported for undefined reason')], )


class WizardListProductsToExport(models.TransientModel):
    _name = "amazon.list.products.export.wizard"
    _description = "Amazon Export Products Wizard"

    supplier_id = fields.Many2one('res.partner',
                                  'Supplier',
                                  domain=[('supplier', '=', True)], )

    backend_id = fields.Many2one('amazon.backend', required=True)

    marketplace_ids = fields.Many2many(comodel_name='amazon.config.marketplace',
                                       string='Markerplaces to export',
                                       relation='amazon_products_export_wizard_marketplace_rel',
                                       default=lambda self:self._compute_marketplaces())

    product_export_ids = fields.One2many('amazon.product.to.export.wizard', 'list_to_export_id', string='Products can be exported')

    product_cant_export_ids = fields.One2many('amazon.product.to.export.wizard', 'list_cant_be_exported_id', string='Products can\'t be exported')

    state = fields.Selection([('draft', 'Borrador'),
                              ('to_sent', 'Products to send'),
                              ('sent', 'Confirmed')],
                             default='draft')

    margin_to_export = fields.Float('Margin to export', default=30, required=True)

    @api.multi
    def name_get(self):
        result = []
        for wizard in self:
            name = 'Wizard to export to Amazon'
            result.append((wizard.id, name))
        return result

    @api.depends('backend_id')
    def _compute_marketplaces(self):
        if self:
            self.marketplace_ids = self.backend_id.marketplace_ids

    def get_wizard_action(self):
        if self._context.get('active_ids', []):
            if self:
                wizard = self
            else:
                backend_id = self.env['amazon.backend'].search([], limit=1)
                if not backend_id:
                    raise UserError(_('There aren\'t backends to get products'))

                wizard = self.create({'backend_id':backend_id.id})

            products = self.env['product.template'].browse(self._context.get('active_ids', []))

            if not products:
                raise UserError(_('There aren\'t products to export'))

            with wizard.backend_id.work_on(self._name) as work:
                importer_product_forid = work.component(model_name='amazon.product.product', usage='amazon.product.data.import')

                for product in products:
                    if product.is_amazon_product:
                        wizard.write({'product_cant_export_ids':[(0, 0, {'product_id':product.id,
                                                                         'can_be_export':'no_is_amazon_product'})]})
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

        return {
            'type':'ir.actions.act_window',
            'name':'Wizard to export products to Amazon',
            'views':[(False, 'form')],
            'res_model':self._name,
            'res_id':wizard.id,
            'flags':{
                'action_buttons':True,
                'sidebar':True,
            },
        }

    def export_products_list(self):
        if not self.product_export_ids:
            raise UserError(_('There aren\'t products to export'))

        if self.margin_to_export and self.margin_to_export < 1:
            raise UserError(_('The margin must be a positive number greater than one'))

        if not self.marketplace_ids:
            raise UserError(_('There aren\'t marketplaces to export'))

        for product in self.product_export_ids:
            for marketplace in self.marketplace_ids:
                row = {}
                row['sku'] = product.product_id.default_code or product.product_id.product_variant_id.default_code
                row['product-id'] = product.asin
                row['product-id-type'] = 'ASIN'
                price = product.product_id.product_variant_id._calc_amazon_price(backend=self.backend_id,
                                                                                 margin=self.margin_to_export,
                                                                                 marketplace=marketplace,
                                                                                 percentage_fee=AMAZON_DEFAULT_PERCENTAGE_FEE)
                row['price'] = ("%.2f" % price).replace('.', marketplace.decimal_currency_separator) if price else ''
                row['minimum-seller-allowed-price'] = ''
                row['maximum-seller-allowed-price'] = ''
                row['item-condition'] = '11'  # We assume the products are new
                row['quantity'] = '0'  # The products stocks allways is 0 when we export these
                row['add-delete'] = 'a'
                row['will-ship-internationally'] = ''
                row['expedited-shipping'] = ''
                row['merchant-shipping-group-name'] = ''
                handling_time = product.product_id.product_variant_id._compute_amazon_handling_time() or ''
                row['handling-time'] = str(handling_time) if price else ''
                row['item_weight'] = ''
                row['item_weight_unit_of_measure'] = ''
                row['item_volume'] = ''
                row['item_volume_unit_of_measure'] = ''
                row['id_mws'] = marketplace.id_mws

                vals = {'backend_id':self.backend_id.id,
                        'type':'Add_products_csv',
                        'model':product.product_id._name,
                        'identificator':product.product_id.id,
                        'data':row,
                        }
                self.env['amazon.feed.tothrow'].create(vals)

        return {
            'type':'ir.actions.act_window',
            'name':'Wizard to export products to Amazon',
            'views':[(False, 'form')],
            'res_model':self.env['product.template']._name,
            'res_id':self.env['product.template'].id,
            'flags':{
                'action_buttons':True,
                'sidebar':True,
            },
        }
