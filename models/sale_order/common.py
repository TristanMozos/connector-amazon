# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2022 Halltic Tech S.L. (https://www.halltic.com)
#                  Tristán Mozos <tristan.mozos@halltic.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import logging
import random
import math

import odoo.addons.decimal_precision as dp
from odoo import models, fields, api, _
from odoo.addons.component.core import Component
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.exceptions import UserError

from ...models.config.common import AMAZON_DEFAULT_PERCENTAGE_FEE

_logger = logging.getLogger(__name__)


class AmazonSaleOrder(models.Model):
    _name = 'amazon.sale.order'
    _inherit = 'amazon.binding'
    _description = 'Amazon Sale Order'
    _inherits = {'sale.order':'odoo_id'}

    def _get_default_currency_id(self):
        return self.env.user.company_id.currency_id.id

    odoo_id = fields.Many2one(comodel_name='sale.order',
                              string='Sale Order',
                              required=True,
                              ondelete='cascade')

    amazon_order_line_ids = fields.One2many(
        comodel_name='amazon.sale.order.line',
        inverse_name='amazon_order_id',
        string='Amazon Order Lines'
    )
    amazon_partner_id = fields.Many2one('amazon.res.partner', "Id of partner", required=False)
    id_amazon_order = fields.Char(string='Amazon Order Id', help='An Amazon-defined order identifier, in 3-7-7 format.', required=True)
    date_purchase = fields.Datetime('The date of purchase', required=False)
    order_status_id = fields.Many2one('amazon.config.order.status', "order_status_id", required=False)
    fullfillment_channel = fields.Selection(selection=[('AFN', 'Amazon Fullfillment'), ('MFN', 'Merchant fullfillment')],
                                            help='How the order was fulfilled: by Amazon (AFN) or by the seller (MFN).', default='MFN', required=True)
    sales_channel = fields.Char('The sales channel of the first item in the order.', required=False, related='marketplace_sale_id.name')

    total_product_amount = fields.Float('The total charge for the products into the order.', required=True, default=0.0)
    total_ship_amount = fields.Float('The total charge for the ship into the order.', required=True, default=0.0)
    total_amount = fields.Float('The total charge for the order.', required=True, default=0.0)
    currency_total_amount = fields.Many2one('res.currency', 'Currency of total amount',
                                            default=_get_default_currency_id,
                                            required=False)
    number_items_shipped = fields.Integer('The number of items shipped.', required=False)
    number_items_unshipped = fields.Integer('The number of items unshipped.', required=False)
    replacement_order = fields.Boolean('The Amazonorder_id value for the order that is being replaced.', default=False)
    replacedorder_id = fields.Char('replacedorder_id', required=False)
    # The anonymized identifier for the Marketplace where the order was placed.
    marketplace_sale_id = fields.Many2one('amazon.config.marketplace', "marketplace_id")
    # The anonymized e-mail address of the buyer.
    buyer_email = fields.Char('buyer_email', required=False, related='amazon_partner_id.odoo_id.email')
    # The name of the buyer.
    buyer_name = fields.Char('buyer_name', required=False, related='amazon_partner_id.alias')
    # fields.Many2one('amazon.order.levelService',
    # 'shipment_service_level_category', required=False) # The shipment service
    # level category of the order. shipment_service_level_category values:
    # Expedited, FreeEconomy, NextDay, SameDay, BuyerTaxInfo SecondDay,
    # Scheduled, Standard
    shipment_service_level_category = fields.Char('shipment_service_level_category', required=False)
    # The start of the time period that you have committed to ship the order.
    # In ISO 8601 date time format.
    date_earliest_ship = fields.Datetime('date_earliest_ship', required=False)
    # The end of the time period that you have committed to ship the order. In
    # ISO 8601 date time format.
    date_latest_ship = fields.Datetime('date_latest_ship', required=False)
    # The start of the time period that you have commited to fulfill the
    # order. In ISO 8601 date time format.
    date_earliest_delivery = fields.Datetime('date_earliest_delivery', required=False)
    # The end of the time period that you have commited to fulfill the order.
    # In ISO 8601 date time format.
    date_latest_delivery = fields.Datetime('date_latest_delivery', required=False)

    is_premium = fields.Boolean('is_premium', required=False)

    is_business = fields.Boolean('is_businnes', required=False)

    is_prime = fields.Boolean('is_prime', required=False)

    order_fee = fields.Float('Order fee',
                             compute='_compute_order_fee',
                             digits=dp.get_precision('Product Price'),
                             store=True,
                             readonly=True)

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, record.id_amazon_order))
        return result

    def export_state_change(self, allowed_states=None,
                            comment=None, notify=None):
        """ Change state of a sales order on Amazon """
        self.ensure_one()
        with self.backend_id.work_on(self._name) as work:
            exporter = work.component(usage='sale.state.exporter')
            return exporter.run(self, allowed_states=allowed_states,
                                comment=comment, notify=notify)

    @api.model
    def import_batch(self, backend, filters=None):
        _super = super(AmazonSaleOrder, self)
        result = _super.import_batch(backend, filters=filters)
        if result and isinstance(result, Exception):
            raise result
        return result

    @api.model
    def import_record(self, backend, external_id):
        _super = super(AmazonSaleOrder, self)
        result = _super.import_record(backend, external_id)
        if not result:
            raise RetryableJobError(msg="The sale of the backend %s hasn\'t could not be imported.\n %s" % (backend.name, external_id),
                                    seconds=random.randint(90, 600))

        if isinstance(result, Exception):
            raise Exception(result)

        return result

    @api.depends('amazon_order_line_ids.fee')
    def _compute_order_fee(self):
        percentage_fee = 0.
        total_fee = 0.

        gen = [line for line in self.amazon_order_line_ids if self.amazon_order_line_ids]
        for line in gen:
            has_percentage = False
            for product_detail in line.amazon_product_id.product_product_market_ids:
                if product_detail.marketplace_id.id == self.marketplace_sale_id.id:
                    percentage_fee = product_detail.percentage_fee
                    has_percentage = True

            if not has_percentage:
                percentage_fee = AMAZON_DEFAULT_PERCENTAGE_FEE

            total_fee = total_fee + ((line.item_price + line.ship_price) * percentage_fee) / 100

        self.order_fee = total_fee


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    amazon_bind_ids = fields.One2many(
        comodel_name='amazon.sale.order',
        inverse_name='odoo_id',
        string="Amazon Bindings",
    )

    amazon_bind_id = fields.Many2one('amazon.sale.order', compute='_compute_amazon_sale_id')

    @api.depends('amazon_bind_ids')
    def _compute_amazon_sale_id(self):
        for p in self:
            p.amazon_bind_id = p.amazon_bind_ids[:1].id

    @api.depends('amazon_bind_ids', 'amazon_bind_ids.amazon_parent_id')
    def get_parent_id(self):
        """ Return the parent order.

        For Amazon sales orders, the amazon parent order is stored
        in the binding, get it from there.
        """
        super(SaleOrder, self).get_parent_id()
        for order in self:
            if not order.amazon_bind_ids:
                continue
            # assume we only have 1 SO in Odoo for 1 SO in Amazon
            assert len(order.amazon_bind_ids) == 1
            amazon_order = order.amazon_bind_ids[0]
            if amazon_order.amazon_parent_id:
                self.parent_id = amazon_order.amazon_parent_id.odoo_id

    def write(self, vals):
        return super(SaleOrder, self).write(vals)

    def _amazon_link_binding_of_copy(self, new):
        # link binding of the canceled order to the new order, so the
        # operations done on the new order will be sync'ed with Amazon
        if self.state != 'cancel':
            return
        binding_model = self.env['amazon.sale.order']
        bindings = binding_model.search([('odoo_id', '=', self.id)])
        bindings.write({'odoo_id':new.id})

        for binding in bindings:
            # the sales' status on Amazon is likely 'canceled'
            # so we will export the new status (pending, processing, ...)
            job_descr = _("Reopen sales order %s") % (binding.external_id,)
            binding.with_delay(
                description=job_descr
            ).export_state_change()

    def copy(self, default=None):
        self_copy = self.with_context(__copy_from_quotation=True)
        new = super(SaleOrder, self_copy).copy(default=default)
        self_copy._amazon_link_binding_of_copy(new)
        return new


class AmazonSaleOrderLine(models.Model):
    _name = 'amazon.sale.order.line'
    _inherit = 'amazon.binding'
    _description = 'Amazon Sale Order Line'
    _inherits = {'sale.order.line':'odoo_id'}

    amazon_order_id = fields.Many2one(comodel_name='amazon.sale.order',
                                      string='Amazon Sale Order',
                                      required=True,
                                      ondelete='cascade',
                                      index=True)

    odoo_id = fields.Many2one(comodel_name='sale.order.line',
                              string='Sale Order Line',
                              required=True,
                              ondelete='cascade')
    backend_id = fields.Many2one(
        related='amazon_order_id.backend_id',
        string='Amazon Backend',
        readonly=True,
        store=True,
        # override 'amazon.binding', can't be INSERTed if True:
        required=False,
    )

    amazon_product_id = fields.Many2one('amazon.product.product')
    id_item = fields.Char()
    qty_shipped = fields.Integer()
    qty_ordered = fields.Integer()
    item_price = fields.Float()
    ship_price = fields.Float()
    fee = fields.Float('Item fee',
                       compute='_compute_item_fee',
                       digits=dp.get_precision('Product Price'),
                       store=True,
                       readonly=True)

    def get_amazon_detail_product(self):
        return self.amazon_product_id.product_product_market_ids.filtered(lambda detail:detail.marketplace_id == self.amazon_order_id.marketplace_sale_id)

    def _compute_item_fee(self):
        percentage = self.get_amazon_detail_product().percentage_fee
        if percentage:
            return ((self.item_price * self.qty_ordered) + self.ship_price) * percentage / 100
        return 0

    @api.model
    def create(self, vals):
        amazon_order_id = vals['amazon_order_id']
        binding = self.env['amazon.sale.order'].browse(amazon_order_id)
        vals['order_id'] = binding.odoo_id.id
        binding = super(AmazonSaleOrderLine, self).create(vals)
        # FIXME triggers function field
        # The amounts (amount_total, ...) computed fields on 'sale.order' are
        # not triggered when amazon.sale.order.line are created.
        # It might be a v8 regression, because they were triggered in
        # v7. Before getting a better correction, force the computation
        # by writing again on the line.
        # line = binding.odoo_id
        # line.write({'price_unit': line.price_unit})
        return binding


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    amazon_bind_ids = fields.One2many(
        comodel_name='amazon.sale.order.line',
        inverse_name='odoo_id',
        string="Amazon Bindings",
    )

    @api.model
    def create(self, vals):
        old_line_id = None
        if self.env.context.get('__copy_from_quotation'):
            # when we are copying a sale.order from a canceled one,
            # the id of the copied line is inserted in the vals
            # in `copy_data`.
            old_line_id = vals.pop('__copy_from_line_id', None)
        new_line = super(SaleOrderLine, self).create(vals)
        if old_line_id:
            # link binding of the canceled order lines to the new order
            # lines, happens when we are using the 'New Copy of
            # Quotation' button on a canceled sales order
            binding_model = self.env['amazon.sale.order.line']
            bindings = binding_model.search([('odoo_id', '=', old_line_id)])
            if bindings:
                bindings.write({'odoo_id':new_line.id})
        return new_line

    def copy_data(self, default=None):
        data = super(SaleOrderLine, self).copy_data(default=default)[0]
        if self.env.context.get('__copy_from_quotation'):
            # copy_data is called by `copy` of the sale.order which
            # builds a dict for the full new sale order, so we lose the
            # association between the old and the new line.
            # Keep a trace of the old id in the vals that will be passed
            # to `create`, from there, we'll be able to update the
            # Amazon bindings, modifying the relation from the old to
            # the new line.
            data['__copy_from_line_id'] = self.id
        return [data]


class SaleOrderAdapter(Component):
    _name = 'amazon.sale.order.adapter'
    _inherit = 'amazon.adapter'
    _apply_on = 'amazon.sale.order'

    def get_lines(self, filters):
        '''
        Method to call at MWS API and return the lines of the order
        :param filters: order
        :return: lines of the order
        '''
        return self._call(method='list_items_from_order', arguments=filters)

    def get_orders(self, arguments):
        try:
            assert arguments
            return self._call(method='get_order', arguments=arguments)
        except AssertionError:
            _logger.error('There aren\'t (%s) parameters for %s' % ('get_order', arguments))
            raise
