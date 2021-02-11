# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2018 Halltic eSolutions S.L. (https://www.halltic.com)
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
import ast
import inspect
import logging
import os
from datetime import datetime, timedelta

from decorator import contextmanager
from odoo import models, fields, api, _
from odoo.exceptions import UserError

from ...components.backend_adapter import AmazonAPI
from odoo.addons.queue_job.job import STARTED, ENQUEUED, PENDING
from ..config.common import AMAZON_NUMBER_MESSAGES_CHANGE_PRICE_RECOVER

_logger = logging.getLogger(__name__)

IMPORT_DELTA_BUFFER = 120  # seconds


class AmazonBackend(models.Model):
    _name = 'amazon.backend'
    _description = 'Amazon Backend'
    _inherit = 'connector.backend'

    name = fields.Char('name', required=True)
    access_key = fields.Char('AWSAccessKeyId', required=True)
    key = fields.Char('secretKey', required=True)
    seller = fields.Char('sellerId', required=True)
    developer = fields.Char('developerId', required=False)
    token = fields.Char('MWSAuthToken', required=True)
    region = fields.Many2one('res.country', 'region', required=True, related='company_id.country_id')  # Region of the marketplaces that the account belongs

    no_sales_order_sync = fields.Boolean(string='Sync sales order', readonly=True)

    stock_sync = fields.Boolean(string='Sync stock products', default=False)

    warehouse_id = fields.Many2one(
        comodel_name='stock.warehouse',
        string='Warehouse',
        required=True,
        help='Warehouse used to compute the '
             'stock quantities.',
    )

    product_binding_ids = fields.One2many(
        comodel_name='amazon.product.product',
        inverse_name='backend_id',
        string='Amazon Products',
        readonly=True,
    )

    sale_ids = fields.One2many(
        comodel_name='amazon.sale.order',
        inverse_name='backend_id',
        string='Amazon Sales',
        readonly=True,
    )

    import_sales_from_date = fields.Datetime(
        string='Import sales from date',
    )

    import_updated_sales_from_date = fields.Datetime(
        string='Import updated sales from date',
    )

    export_updated_prices = fields.Datetime(
        string='Export updated prices',
    )

    import_feedbacks_from_date = fields.Datetime(
        string='Import feedbacks from date',
    )

    sale_prefix = fields.Char(
        string='Sale Prefix',
        help="A prefix put before the name of imported sales orders.\n"
             "For instance, if the prefix is 'amz-', the sales "
             "order 100000692 in Amazon, will be named 'amz-100000692' "
             "in Odoo.",
        default='amz-'
    )

    company_id = fields.Many2one(
        comodel_name='res.company',
        related='warehouse_id.company_id',
        string='Company',
        readonly=True,
    )

    fba_warehouse_id = fields.Many2one(
        comodel_name='stock.warehouse', string='FBA Warehouse',
        track_visibility='onchange',
        helper="Products are physically stored in an Amazon warehouse.\n"
               "Define a dedicated warehouse for this case")

    team_id = fields.Many2one(comodel_name='crm.team', string='Sales Team')

    marketplace_ids = fields.Many2many(comodel_name='amazon.config.marketplace', string='Markerplaces of backend')

    shipping_template_ids = fields.One2many(comodel_name='amazon.shipping.template',
                                            inverse_name='backend_id',
                                            string='Shipping Templates', )

    # Min and max margin stablished for the calculation of the price on product and product price details if these do not be informed
    change_prices = fields.Selection(string='Change prices', selection=[('0', 'No'), ('1', 'Yes'), ])
    min_margin = fields.Float('Minimal margin', default=None)
    max_margin = fields.Float('Maximal margin', default=None)
    units_to_change = fields.Float('Currency units to change', digits=(3, 2), default=0.01)
    min_price_margin_value = fields.Float('Min price margin value', digits=(3, 2))

    sqs_account_id = fields.Many2one('amazon.config.sqs.account', 'SQS account')

    _sql_constraints = [
        ('sale_prefix_uniq', 'unique(sale_prefix)',
         "A backend with the same sale prefix already exists")
    ]

    def check_same_import_jobs(self, model, key, backend=None):
        if not backend:
            backend = self
        job = self.env['queue.job'].search([('channel', '=', 'root.amazon'),
                                            ('state', 'in', (STARTED, ENQUEUED, PENDING)),
                                            ('func_string', 'ilike', str(backend)),
                                            ('model_name', 'ilike', model),
                                            ('func_string', 'ilike', key)])
        if job:
            return True
        return False

    def get_templates_from_products(self):
        self._cr.execute(""" SELECT DISTINCT
                                apd.marketplace_id,
                                apd.merchant_shipping_group
                            FROM
                                amazon_product_product_detail apd
                            WHERE
                                product_id IN
                                    (SELECT
                                        id
                                     FROM
                                        amazon_product_product
                                     WHERE
                                        backend_id=%s)
                                AND
                                apd.marketplace_id || ' -|- ' || apd.merchant_shipping_group NOT IN
                                (SELECT ast.marketplace_id || ' -|- ' || ast.name FROM amazon_shipping_template ast WHERE backend_id=%s)
                            """, (self.id, self.id))

        shipping_templates = self._cr.dictfetchall()
        for ship_template in shipping_templates:
            self.write({'shipping_template_ids':[(0, 0, {'backend_id':self.id,
                                                         'name':ship_template['merchant_shipping_group'],
                                                         'marketplace_id':ship_template['marketplace_id']})
                                                 ]})

    @api.model
    def _get_crypt_codes_marketplaces(self):
        if self:
            mp = []
            for mp_rs in self.marketplace_ids:
                mp.append(mp_rs.id_mws)
            return mp

    def _get_marketplace_default(self):
        self.ensure_one()
        for market in self.marketplace_ids:
            if market.country_id.id == self.region.id:
                return market
        return

    @contextmanager
    def work_on(self, model_name, **kwargs):
        self.ensure_one()
        # We create a Amazon Client API here, so we can create the
        # client once (lazily on the first use) and propagate it
        # through all the sync session, instead of recreating a client
        # in each backend adapter usage.
        with AmazonAPI(self) as amazon_api:
            _super = super(AmazonBackend, self)
            # from the components we'll be able to do: self.work.amazon_api
            with _super.work_on(
                    model_name, amazon_api=amazon_api, **kwargs) as work:
                yield work

    def _import_product_product(self):
        for backend in self:
            try:
                _logger.info('Report is going to generated for %s' % backend.name)
                user = backend.warehouse_id.company_id.user_tech_id
                if not user:
                    user = self.env['res.users'].browse(self.env.uid)

                report_binding_model = self.env['amazon.report']
                if user != self.env.user:
                    report_binding_model = report_binding_model.sudo(user)

                filters = {'method':'submit_inventory_request'}
                report_id = report_binding_model.import_batch(backend, filters=filters)

                if report_id and report_id['report_ids']:
                    delayable = report_binding_model.with_delay(priority=1, eta=datetime.now() + timedelta(minutes=10))
                    filters = {'method':'get_inventory'}
                    filters['report_id'] = [report_id['report_ids']]  # Send a list for getattr call
                    delayable.description = 'Generate inventory report to: %s' % backend.name
                    delayable.import_batch(backend, filters=filters)

                _logger.info('Report has been generated for %s' % backend.name)
            except Exception as e:
                _logger.error('Error generating report on backend %s: %s' % (backend.name, e.message))

        _logger.info('Report is done')

        # On Amazon we haven't a modified date on products and we need import all inventory
        # To import this, we need throw a report request, when this had been generated, we import all the product data
        # We are putting 5 minutes to launch the delayable job
        return True

    def _export_product_product(self):
        sup_products = self.env['product.supplierinfo'].search([('name.supplier', '=', True),
                                                                '|',
                                                                ('name.automatic_export_products', '=', True),
                                                                ('name.automatic_export_all_markets', '=', True), ], order='product_id')

        product_id = 0
        for sup_product in sup_products:
            if product_id == 0 or sup_product.product_id.id != product_id:
                sup_product.export_products_from_supplierinfo()
            product_id = sup_product.product_id.id


    def _import_sale_orders(self,
                            import_start_time=None,
                            import_end_time=None,
                            generate_report=False,
                            update_import_date=True):

        for backend in self:
            if not backend.import_updated_sales_from_date:
                backend.import_updated_sales_from_date = backend.import_sales_from_date

            if not import_end_time:
                import_end_time = datetime.strptime(datetime.today().strftime('%Y-%m-%d %H:%M:%S'), '%Y-%m-%d %H:%M:%S') - timedelta(minutes=2)

            # If the start date to get sales is empty we put now as date
            if not import_start_time:
                if backend.import_sales_from_date:
                    import_start_time = backend.import_sales_from_date
                else:
                    import_start_time = import_end_time

            if generate_report:
                report_binding_model = self.env['amazon.report']

                filters = {'method':'submit_sales_request'}
                filters['date_start'] = import_start_time.isoformat()
                filters['date_end'] = import_end_time.isoformat()
                report_id = report_binding_model.import_batch(backend, filters=filters)

                if report_id:
                    delayable = report_binding_model.with_delay(priority=3, eta=datetime.now() + timedelta(minutes=5))
                    filters = {'method':'get_sales'}
                    filters['report_id'] = [report_id['report_ids']]
                    delayable.description = 'Generate sales report to: %s' % backend.name
                    delayable.import_batch(backend, filters=filters)
            else:
                sale_binding_model = self.env['amazon.sale.order'].sudo(True)
                filters = {'date_start':import_start_time.isoformat(), 'date_end':import_end_time.isoformat()}
                sale_binding_model.import_batch(backend, filters=filters)

            if update_import_date:
                backend.write({'import_sales_from_date':import_end_time})

        return True

    def _import_updated_sales(self,
                              import_start_time=None,
                              import_end_time=None,
                              update_import_date=True):

        for backend in self:
            sale_binding_model = self.env['amazon.sale.order'].sudo(True)

            if not import_end_time:
                # We minus two minutes to now time
                import_end_time = datetime.strptime(datetime.today().strftime('%Y-%m-%d %H:%M:%S'), '%Y-%m-%d %H:%M:%S') - timedelta(minutes=2)
            if not import_start_time:
                if backend.import_sales_from_date:
                    import_start_time = backend.import_updated_sales_from_date
                else:
                    import_start_time = import_end_time

            sale_binding_model.import_batch(backend, filters={'update_start':import_start_time.isoformat(),
                                                              'update_end':import_end_time.isoformat(),
                                                              'update_sales_flag':True})
            if update_import_date:
                backend.write({'import_updated_sales_from_date':import_end_time})

    def _import_customer_feedback_orders(self,
                            import_start_time=None,
                            import_end_time=None):

        for backend in self:
            if not import_end_time:
                import_end_time = datetime.strptime(datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
                                                    '%Y-%m-%d %H:%M:%S') - timedelta(minutes=2)

            # If the start date to get sales is empty we put now as date
            if not import_start_time:
                if backend.import_feedbacks_from_date:
                    import_start_time = datetime.strptime(backend.import_feedbacks_from_date, '%Y-%m-%d %H:%M:%S')
                else:
                    import_start_time = import_end_time

            report_binding_model = self.env['amazon.report']

            filters = {'method': 'submit_feedbacks_report_request'}
            filters['date_start'] = import_start_time.isoformat()
            filters['date_end'] = import_end_time.isoformat()
            report_id = report_binding_model.import_batch(backend, filters=filters)

            if report_id:
                delayable = report_binding_model.with_delay(priority=7, eta=datetime.now() + timedelta(minutes=10))
                filters = {'method': 'get_customer_feedbacks'}
                filters['report_id'] = [report_id['report_ids']]
                delayable.description = 'Generate customer feedbacks report to: %s' % backend.name
                delayable.import_batch(backend, filters=filters)

        return True


    @api.model
    def _update_product_stock_qty_prices(self):
        for backend in self:
            product_binding_model = self.env['amazon.product.product'].sudo(True)
            # We are going to export the stock and prices changes
            product_binding_model.export_batch(backend)

    def _fix_amazon_data(self):
        for backend in self:
            fix_data_model = self.env['amazon.fix.data'].sudo(True)
            # We are going to import the initial prices, fees and prices changes
            fix_data_model.run_delayed_jobs(backend)
            break

        return True


    def _throw_feeds(self):
        for backend in self:
            _logger.info('connector_amazon [%s][%s] log: Throw feeds init with %s backend' % (os.getpid(), inspect.stack()[0][3], backend.name))
            user = backend.warehouse_id.company_id.user_tech_id
            if not user:
                user = self.env['res.users'].browse(self.env.uid)

            with backend.work_on(self._name) as work:
                exporter_stock = work.component(model_name='amazon.feed', usage='amazon.submit.feeds')
                exporter_stock.submit_feeds()

    @api.model
    def _amazon_backend(self, callback, domain=None):
        if domain is None:
            domain = []
        backends = self.search(domain)
        if backends:
            getattr(backends, callback)()

    @api.model
    def _scheduler_import_sale_orders(self, domain=None):
        self._amazon_backend('_import_sale_orders', domain=domain)
        self._amazon_backend('_import_updated_sales', domain=domain)

    @api.model
    def _scheduler_import_product_product(self, domain=None):
        self._amazon_backend('_import_product_product', domain=domain)

    @api.model
    def _scheduler_get_customer_feedback_orders(self, domain=None):
        self._amazon_backend('_import_customer_feedback_orders', domain=domain)

    @api.model
    def _scheduler_export_product_product(self, domain=None):
        self._amazon_backend('_export_product_product', domain=domain)

    @api.model
    def _scheduler_update_product_prices_stock_qty(self, domain=None):
        self._amazon_backend('_update_product_stock_qty_prices', domain=domain)

    @api.model
    def _scheduler_connector_amazon_fix_data(self, domain=None):
        self._amazon_backend('_fix_amazon_data', domain=domain)

    @api.model
    def _scheduler_throw_feeds(self, domain=None):
        self._amazon_backend('_throw_feeds', domain=domain)

