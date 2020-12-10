# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import datetime
from datetime import datetime, timedelta

from odoo import fields, models, api, _
from odoo.exceptions import UserError


class WizardMigrateBackendProducts(models.TransientModel):
    _name = "amazon.migrate.backend.products.wizard"
    _description = "Wizard to migrate amazon products from backend"


    backend_id = fields.Many2one('amazon.backend', required=True)
    marketplace_ids = fields.Many2many(comodel_name='amazon.config.marketplace', string='Markerplaces to migrate', compute='_onchange_marketplaces')
    product_ids = fields.Many2many(comodel_name='amazon.product.product', relation='migrate_products_backend_wizard_rel', string='Products')

    @api.multi
    def name_get(self):
        result = []
        for wizard in self:
            name = 'Wizard to migrate amazon products from backend'
            result.append((wizard.id, name))
        return result

    @api.onchange('backend_id')
    def _onchange_marketplaces(self):
        for wizard in self:
            if wizard.backend_id:
                wizard.marketplace_ids = wizard.backend_id.marketplace_ids

    @api.multi
    def migrate_products(self):
        """
        Method to create de feed to migrate the product from their backend to new backend
        :return:
        """
        if self.product_ids:
            for amazon_product in self.product_ids:
                if amazon_product.backend_id.id!=self.backend_id.id:
                    data = {'new_backend_id': self.backend_id.id,
                            'marketplace_ids': self.marketplace_ids.mapped('id'),
                            'amazon_product_id': amazon_product.id,
                            }

                    vals = {'backend_id': amazon_product.backend_id.id,
                            'type': 'Migrate_backend',
                            'model': self._name,
                            'identificator': self.id,
                            'data': data,
                            }
                    self.env['amazon.feed.tothrow'].create(vals)

        return {'type': 'ir.actions.client', 'tag': 'history_back'}

    @api.multi
    def get_amazon_products_to_migrate(self):
        """
        Method to get amazon products for migrate
        :return:
        """
        if self._context.get('active_ids', []):
            backend_id = self.env['amazon.backend'].search([], limit=1)
            wizard = self.create({'backend_id': backend_id.id})
            for id_prod in self._context.get('active_ids', []):
                wizard.write({'product_ids':[(4, id_prod)]})


            return {
                'type': 'ir.actions.act_window',
                'name': 'Wizard to migrate amazon products from backend',
                'views': [(False, 'form')],
                'res_model': self._name,
                'res_id': wizard.id,
                'flags': {
                    'action_buttons': True,
                    'sidebar': True,
                },
            }

        raise UserError(_('There aren\'t products to migrate.'))

    @api.multi
    def get_products_to_migrate(self, product, product_computed=[]):
        """
        Get all products depends of product
        :param product:
        :param product_computed:
        :return:
        """
        if product.type == 'product' and product.id not in product_computed:
            product_computed.append(product.id)
            # First, we are going up on the LoM relationship
            if product.bom_ids:
                for bom in product.bom_ids:
                    for line_bom in bom.bom_line_ids:
                        self.get_products_to_migrate(line_bom.product_id, product_computed=product_computed)
            # Second, we are going to search if any product have this product on LoM
            bom_childs = self.env['mrp.bom.line'].search([('product_id', '=', product.id)])
            for line_bom in bom_childs:
                self.get_products_to_migrate(line_bom.bom_id.product_tmpl_id.product_variant_id,
                                                     product_computed=product_computed)

    @api.multi
    def get_products_from_supplier_to_migrate(self):
        """

        :return:
        """
        if self._context.get('active_ids', []):
            supplier = self.env['res.partner'].browse(self._context.get('active_ids', []))
            sup_products = self.env['product.supplierinfo'].search([('name', '=', supplier.id)])
            there_are_products=False
            if sup_products:
                backend_id = self.env['amazon.backend'].search([], limit=1)
                wizard = self.create({'backend_id': backend_id.id})
                for sup_prod in sup_products:
                    product_ids = []
                    self.get_products_to_migrate(product=sup_prod.product_id, product_computed=product_ids)
                    for prod_id in product_ids:
                        prod = self.env['product.product'].browse(prod_id)
                        if prod and prod.amazon_bind_ids:
                            for amazon_prod in prod.amazon_bind_ids:
                                there_are_products = True
                                wizard.write({'product_ids': [(4, amazon_prod.id)]})

                if there_are_products:
                    return {
                        'type': 'ir.actions.act_window',
                        'name': 'Wizard to migrate amazon products from backend',
                        'views': [(False, 'form')],
                        'res_model': self._name,
                        'res_id': wizard.id,
                        'flags': {
                            'action_buttons': True,
                            'sidebar': True,
                        },
                    }

        raise UserError(_('There aren\'t products to migrate.'))
