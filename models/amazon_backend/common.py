# -*- coding: utf-8 -*-
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from datetime import datetime, timedelta

from decorator import contextmanager
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.addons.connector.checkpoint import checkpoint

from ...components.backend_adapter import AmazonAPI

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

    _sql_constraints = [
        ('sale_prefix_uniq', 'unique(sale_prefix)',
         "A backend with the same sale prefix already exists")
    ]

    @api.model
    def _get_crypt_codes_marketplaces(self):
        if self:
            mp = []
            for mp_rs in self.marketplace_ids:
                mp.append(mp_rs.id_mws)
            return mp

    @api.multi
    def _get_marketplace_default(self):
        self.ensure_one()
        for market in self.marketplace_ids:
            if market.country_id.id == self.region.id:
                return market
        return

    @api.multi
    def add_checkpoint(self, record):
        self.ensure_one()
        record.ensure_one()
        return checkpoint.add_checkpoint(self.env, record._name, record.id,
                                         self._name, self.id)

    @contextmanager
    @api.multi
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

    @api.multi
    def _import_product_product(self):
        import_start_time = datetime.now()
        for backend in self:
            user = backend.warehouse_id.company_id.user_tech_id
            if not user:
                user = self.env['res.users'].browse(self.env.uid)

            report_binding_model = self.env['amazon.report']
            if user != self.env.user:
                report_binding_model = report_binding_model.sudo(user)

            filters = {'method':'submit_inventory_request'}
            report_id = report_binding_model.import_batch(backend, filters=filters)

            if report_id and report_id['report_ids']:
                delayable = report_binding_model.with_delay(priority=1, eta=datetime.now() + timedelta(minutes=5))
                filters = {'method':'get_inventory'}
                filters['report_id'] = [report_id['report_ids']]  # Send a list for getattr call
                delayable.import_batch(backend, filters=filters)

        # On Amazon we haven't a modified date on products and we need import all inventory
        # To import this, we need throw a report request, when this had been generated, we import all the product data
        # We are putting 5 minutes to launch the delayable job
        return True

    @api.multi
    def _import_sale_orders(self, import_start_time=None, import_end_time=datetime.now(), generate_report=True):
        for backend in self:
            user = backend.warehouse_id.company_id.user_tech_id
            if not user:
                user = self.env['res.users'].browse(self.env.uid)

            if generate_report:
                report_binding_model = self.env['amazon.report']
                if user != self.env.user:
                    report_binding_model = report_binding_model.sudo(user)

                if not backend.import_updated_sales_from_date:
                    backend.import_updated_sales_from_date = backend.import_sales_from_date

                # If the start date to get sales is empty we put now as date
                if import_start_time == None:
                    if backend.import_sales_from_date:
                        import_start_time = datetime.strptime(backend.import_sales_from_date, '%Y-%m-%d %H:%M:%S')
                    else:
                        import_start_time = import_end_time

                filters = {'method':'submit_sales_request'}
                filters['date_start'] = import_start_time.isoformat()
                filters['date_end'] = import_end_time.isoformat()
                report_id = report_binding_model.import_batch(backend, filters=filters)

                if report_id:
                    delayable = report_binding_model.with_delay(priority=5, eta=datetime.now() + timedelta(minutes=5))
                    filters = {'method':'get_sales'}
                    filters['report_id'] = report_id['report_ids']
                    delayable.import_batch(backend, filters=filters)
                    backend.write({'import_sales_from_date':import_end_time})

            else:
                sale_binding_model = self.env['amazon.sale.order']
                sale_binding_model.import_batch(backend, filters={'date_start':import_start_time.isoformat(), 'date_end':import_end_time.isoformat()})
                return True

        return True

    @api.multi
    def _import_updated_sales(self, import_start_time=None, import_end_time=datetime.now()):
        for backend in self:
            if import_start_time == None:
                if backend.import_sales_from_date:
                    import_start_time = datetime.strptime(backend.import_updated_sales_from_date, '%Y-%m-%d %H:%M:%S')
                else:
                    import_start_time = import_end_time
            sale_binding_model = self.env['amazon.sale.order']
            sale_binding_model.import_batch(backend, filters={'update_start':import_start_time.isoformat(), 'update_end':import_end_time.isoformat()})
            backend.write({'import_updated_sales_from_date':import_end_time})

    @api.model
    def _update_product_prices(self):
        export_end_time = datetime.now()
        for backend in self:
            user = backend.warehouse_id.company_id.user_tech_id
            if not user:
                user = self.env['res.users'].browse(self.env.uid)

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
    def _scheduler_update_product_stock_qty(self, domain=None):
        self._amazon_backend('update_product_stock_qty', domain=domain)

    @api.model
    def _scheduler_update_product_prices(self, domain=None):
        self._amazon_backend('_update_product_prices', domain=domain)
