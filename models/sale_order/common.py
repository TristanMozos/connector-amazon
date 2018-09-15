# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
import xmlrpclib
import math

import odoo.addons.decimal_precision as dp
from odoo import models, fields, api, _, exceptions
from odoo.addons.component.core import Component
from odoo.addons.connector.exception import IDMissingInBackend
from odoo.addons.queue_job.exception import FailedJobError, RetryableJobError
from odoo.addons.queue_job.job import job
from odoo.exceptions import UserError

from ...components.backend_adapter import AMAZON_DATETIME_FORMAT

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

    @job(default_channel='root.amazon')
    @api.multi
    def export_state_change(self, allowed_states=None,
                            comment=None, notify=None):
        # TODO develop a wizard that can cancel the order
        raise exceptions.except_orm('Error', 'This method need will be developed, you need to go to the odoo to cancel de order')

    @job(default_channel='root.amazon')
    @api.model
    def import_batch(self, backend, filters=None):
        _super = super(AmazonSaleOrder, self)
        return _super.import_batch(backend, filters=filters)

    @job(default_channel='root.amazon')
    @api.model
    def import_record(self, backend, external_id):
        _super = super(AmazonSaleOrder, self)
        result = _super.import_record(backend, external_id)
        if not result:
            raise RetryableJobError("The sale of the backend %s hasn\'t could not be imported.\n %s", backend.name, external_id, 60)

    @api.depends('amazon_order_line_ids.fee')
    def _compute_order_fee(self):
        category_percentage_fee = 0.
        total_fee = 0.

        gen = [line for line in self.amazon_order_line_ids if self.amazon_order_line_ids]
        for line in gen:
            has_percentage = False
            for product_detail in line.amazon_product_id.product_product_market_ids:
                if product_detail.marketplace_id.id == self.marketplace_sale_id.id and product_detail.category_id:
                    category_percentage_fee = product_detail.category_id.percentage
                    has_percentage = True

            if not has_percentage:
                category_percentage_fee = self.env['amazon.config.product.category'].search([('name', '=', 'default')]).percentage

            total_fee = total_fee + ((line.item_price + line.ship_price) * category_percentage_fee) / 100

        self.order_fee = total_fee


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    amazon_bind_ids = fields.One2many(
        comodel_name='amazon.sale.order',
        inverse_name='odoo_id',
        string="Amazon Bindings",
    )

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

    def _amazon_cancel(self):
        """ Cancel sales order on Amazon

        Do not export the other state changes, Amazon handles them itself
        when it receives shipments and invoices.
        """
        for order in self:
            old_state = order.state
            if old_state == 'cancel':
                continue  # skip if already canceled
            for binding in order.amazon_bind_ids:
                job_descr = _("Cancel sales order %s") % (binding.external_id,)
                binding.with_delay(
                    description=job_descr
                ).export_state_change(allowed_states=['cancel'])

    @api.multi
    def write(self, vals):
        if vals.get('state') == 'cancel':
            self._amazon_cancel()
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

    @api.multi
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

    def _compute_item_fee(self):
        return 0.

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

    @api.multi
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

    @api.multi
    def get_lines(self, filters):
        '''
        Method to call at MWS API and return the lines of the order
        :param filters: order
        :return: lines of the order
        '''
        return self._call(method='list_items_from_order', arguments=filters)


class AccountTax(models.Model):
    _inherit = 'account.tax'

    @api.multi
    def compute_all_with_taxes(self, price_unit, currency=None, quantity=1.0, product=None, partner=None):
        """ Returns all information required to apply taxes (in self + their children in case of a tax goup).
            We consider the sequence of the parent for group of taxes.
                Eg. considering letters as taxes and alphabetic order as sequence :
                [G, B([A, D, F]), E, C] will be computed as [A, D, F, C, E, G]

        RETURN: {
            'total_excluded': 0.0,    # Total without taxes
            'total_included': 0.0,    # Total with taxes
            'taxes': [{               # One dict for each tax in self and their children
                'id': int,
                'name': str,
                'amount': float,
                'sequence': int,
                'account_id': int,
                'refund_account_id': int,
                'analytic': boolean,
            }]
        } """

        # 1) Flatten the taxes.

        def collect_taxes(self, all_taxes=None):
            # Collect all the taxes recursively ordered by the sequence.
            # Example:
            # group | seq | sub-group |
            # ------------|-----------|
            #       |  1  |           |
            # ------------|-----------|
            #   t   |  2  |  | seq |  |
            #       |     |  |  4  |  |
            #       |     |  |  5  |  |
            #       |     |  |  6  |  |
            #       |     |           |
            # ------------|-----------|
            #       |  3  |           |
            # ------------|-----------|
            # Result: 1-4-5-6-3
            if not all_taxes:
                all_taxes = self.env['account.tax']
            for tax in self.sorted(key=lambda r:r.sequence):
                if tax.amount_type == 'group':
                    all_taxes = collect_taxes(tax.children_tax_ids, all_taxes)
                else:
                    all_taxes += tax
            return all_taxes

        taxes = collect_taxes(self)

        # 2) Avoid dealing with taxes mixing price_include=False && include_base_amount=True
        # with price_include=True

        base_excluded_flag = False  # price_include=False && include_base_amount=True
        included_flag = False  # price_include=True
        for tax in taxes:
            if tax.price_include:
                included_flag = True
            elif tax.include_base_amount:
                base_excluded_flag = True
            if base_excluded_flag and included_flag:
                raise UserError(_('Unable to mix any taxes being price included with taxes affecting the base amount but not included in price.'))

        # 3) Deal with the rounding methods

        if len(self) == 0:
            company_id = self.env.user.company_id
        else:
            company_id = self[0].company_id
        if not currency:
            currency = company_id.currency_id

        # By default, for each tax, tax amount will first be computed
        # and rounded at the 'Account' decimal precision for each
        # PO/SO/invoice line and then these rounded amounts will be
        # summed, leading to the total amount for that tax. But, if the
        # company has tax_calculation_rounding_method = round_globally,
        # we still follow the same method, but we use a much larger
        # precision when we round the tax amount for each line (we use
        # the 'Account' decimal precision + 5), and that way it's like
        # rounding after the sum of the tax amounts of each line
        prec = currency.decimal_places

        # In some cases, it is necessary to force/prevent the rounding of the tax and the total
        # amounts. For example, in SO/PO line, we don't want to round the price unit at the
        # precision of the currency.
        # The context key 'round' allows to force the standard behavior.
        round_tax = False if company_id.tax_calculation_rounding_method == 'round_globally' else True
        round_total = True
        if 'round' in self.env.context:
            round_tax = bool(self.env.context['round'])
            round_total = bool(self.env.context['round'])

        if not round_tax:
            prec += 5

        # 4) Iterate the taxes in the reversed sequence order to retrieve the initial base of the computation.
        #     tax  |  base  |  amount  |
        # /\ ----------------------------
        # || tax_1 |  XXXX  |          | <- we are looking for that, it's the total_excluded
        # || tax_2 |        |          |
        # || tax_3 |        |          |
        # ||  ...  |   ..   |    ..    |
        #    ----------------------------

        def recompute_base(base_amount, fixed_amount, percent_amount):
            # Recompute the new base amount based on included fixed/percent amount and the current base amount.
            # Example:
            #  tax  |  amount  |
            # ------------------
            # tax_1 |   10%    |
            # tax_2 |   15     |
            # tax_3 |   20%    |
            # ------------------
            # if base_amount = 145, the new base is computed as:
            # (145 - 15) / (1.0 + ((10 + 20) / 100.0)) = 130 / 1.3 = 100
            if fixed_amount == 0.0 and percent_amount == 0.0:
                return base_amount
            return (base_amount - fixed_amount) / (1.0 + percent_amount / 100.0)

        base = round(price_unit * quantity, prec)

        # For the computation of move lines, we could have a negative base value.
        # In this case, compute all with positive values and negative them at the end.
        if base < 0:
            base = -base
            sign = -1
        else:
            sign = 1

        # Keep track of the accumulated included fixed/percent amount.
        incl_fixed_amount = incl_percent_amount = 0
        for tax in reversed(taxes):
            if tax.include_base_amount:
                base = recompute_base(base, incl_fixed_amount, incl_percent_amount)
                incl_fixed_amount = incl_percent_amount = 0
            if tax.price_include:
                if tax.amount_type == 'fixed':
                    incl_fixed_amount += tax.amount
                elif tax.amount_type == 'percent':
                    incl_percent_amount += tax.amount
        # Start the computation of accumulated amounts at the total_excluded value.
        total_excluded = total_included = base = recompute_base(base, incl_fixed_amount, incl_percent_amount)

        # 5) Iterate the taxes in the sequence order to fill missing base/amount values.
        #      tax  |  base  |  amount  |
        # ||  ----------------------------
        # ||  tax_1 |   OK   |   XXXX   |
        # ||  tax_2 |  XXXX  |   XXXX   |
        # ||  tax_3 |  XXXX  |   XXXX   |
        # \/  ...  |   ..   |    ..    |
        #     ----------------------------
        taxes_vals = []
        for tax in taxes:
            # Compute the amount of the tax but don't deal with the price_include because it's already
            # took into account on the base amount except for 'division' tax:
            # (tax.amount_type == 'percent' && not tax.price_include)
            # == (tax.amount_type == 'division' && tax.price_include)
            tax_amount = tax._compute_amount_with_taxes(base, quantity)
            if not round_tax:
                tax_amount = round(tax_amount, prec)
            else:
                tax_amount = currency.round(tax_amount)

            # Suppose:
            # seq | amount | incl | incl_base | base | amount
            # -----------------------------------------------
            #  1  |   10 % |   t  |     t     | 100.0 | 10.0
            # -----------------------------------------------
            # ... the next computation must be done using 100.0 + 10.0 = 110.0 as base but
            # the tax base of this tax will be 100.0.
            tax_base = base
            if tax.include_base_amount:
                base += tax_amount

            # The total_included amount is computed as the sum of total_excluded with all tax_amount
            total_included += tax_amount

            taxes_vals.append({
                'id':tax.id,
                'name':tax.with_context(**{'lang':partner.lang} if partner else {}).name,
                'amount':sign * tax_amount,
                'base':round(sign * tax_base, prec),
                'sequence':tax.sequence,
                'account_id':tax.account_id.id,
                'refund_account_id':tax.refund_account_id.id,
                'analytic':tax.analytic,
            })

        return {
            'taxes':taxes_vals,
            'total_excluded':sign * (currency.round(total_excluded) if round_total else total_excluded),
            'total_included':sign * (currency.round(total_included) if round_total else total_included),
            'base':round(sign * base, prec),
        }

    def _compute_amount_taxes_include(self, base_amount, quantity=1.0):
        """ Returns the amount of a single tax. base_amount is the actual amount on which the tax is applied, which is
            price_unit * quantity eventually affected by previous taxes (if tax is include_base_amount XOR price_include)
        """
        self.ensure_one()
        price_include = True
        if self.amount_type == 'fixed':
            # Use copysign to take into account the sign of the base amount which includes the sign
            # of the quantity and the sign of the price_unit
            # Amount is the fixed price for the tax, it can be negative
            # Base amount included the sign of the quantity and the sign of the unit price and when
            # a product is returned, it can be done either by changing the sign of quantity or by changing the
            # sign of the price unit.
            # When the price unit is equal to 0, the sign of the quantity is absorbed in base_amount then
            # a "else" case is needed.
            if base_amount:
                return math.copysign(quantity, base_amount) * self.amount
            else:
                return quantity * self.amount
        if (self.amount_type == 'percent' and not price_include) or (self.amount_type == 'division' and price_include):
            return base_amount * self.amount / 100
        if self.amount_type == 'percent' and price_include:
            return base_amount - (base_amount / (1 + self.amount / 100))
        if self.amount_type == 'division' and not price_include:
            return base_amount / (1 - self.amount / 100) - base_amount
