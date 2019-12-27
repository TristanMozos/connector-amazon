# -*- coding: utf-8 -*-
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import ast
import inspect
import logging
from datetime import datetime, timedelta

from decorator import contextmanager
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.addons.connector.checkpoint import checkpoint

from odoo.addons.queue_job.job import STARTED, ENQUEUED, PENDING
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
    change_prices = fields.Boolean('Change the prices', default=False)
    min_margin = fields.Float('Minimal margin', default=None)
    max_margin = fields.Float('Minimal margin', default=None)
    units_to_change = fields.Float(digits=(3, 2), default=0.01)
    type_unit_to_change = fields.Selection(selection=[('price', 'Price (€)'),
                                                      ('percentage', 'Percentage (%)')],
                                           string='Type of unit',
                                           default='price')
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
    def _import_export_product_product(self):
        for backend in self:
            _logger.info('Report is going to generated for %s at %s' % backend.name, datetime.now())
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
                delayable.import_batch(backend, filters=filters)

            _logger.info('Report has been generated for %s at %s' % backend.name, datetime.now())

        _logger.info('Report is done')
        sup_products = self.env['product.supplierinfo'].search([('name.supplier', '=', True),
                                                                ('name.automatic_export_products', '=', True),
                                                                ('product_id.amazon_bind_ids', '=', False)])

        for sup_product in sup_products:
            _logger.info('Report has been generated for %s at %s' % backend.name, datetime.now())
            sup_product.export_products_from_supplierinfo()

        # On Amazon we haven't a modified date on products and we need import all inventory
        # To import this, we need throw a report request, when this had been generated, we import all the product data
        # We are putting 5 minutes to launch the delayable job
        return True

    @api.multi
    def _import_sale_orders(self,
                            import_start_time=None,
                            import_end_time=None,
                            generate_report=False,
                            update_import_date=True):

        for backend in self:
            user = backend.warehouse_id.company_id.user_tech_id
            if not user:
                user = self.env['res.users'].browse(self.env.uid)

            if not backend.import_updated_sales_from_date:
                backend.import_updated_sales_from_date = backend.import_sales_from_date

            if not import_end_time:
                import_end_time = datetime.strptime(datetime.today().strftime('%Y-%m-%d %H:%M:%S'), '%Y-%m-%d %H:%M:%S') - timedelta(minutes=2)

            # If the start date to get sales is empty we put now as date
            if not import_start_time:
                if backend.import_sales_from_date:
                    import_start_time = datetime.strptime(backend.import_sales_from_date, '%Y-%m-%d %H:%M:%S')
                else:
                    import_start_time = import_end_time

            if generate_report:
                report_binding_model = self.env['amazon.report']

                filters = {'method':'submit_sales_request'}
                filters['date_start'] = import_start_time.isoformat()
                filters['date_end'] = import_end_time.isoformat()
                report_id = report_binding_model.import_batch(backend, filters=filters)

                if report_id:
                    delayable = report_binding_model.with_delay(priority=4, eta=datetime.now() + timedelta(minutes=5))
                    filters = {'method':'get_sales'}
                    filters['report_id'] = [report_id['report_ids']]
                    delayable.import_batch(backend, filters=filters)
            else:
                sale_binding_model = self.env['amazon.sale.order']
                if user != self.env.user:
                    sale_binding_model = sale_binding_model.sudo(user)
                filters = {'date_start':import_start_time.isoformat(), 'date_end':import_end_time.isoformat()}
                sale_binding_model.import_batch(backend, filters=filters)

            if update_import_date:
                backend.write({'import_sales_from_date':import_end_time})

        return True

    @api.multi
    def _import_updated_sales(self,
                              import_start_time=None,
                              import_end_time=None,
                              update_import_date=True):

        for backend in self:
            user = backend.warehouse_id.company_id.user_tech_id
            if not user:
                user = self.env['res.users'].browse(self.env.uid)
            sale_binding_model = self.env['amazon.sale.order']
            if user != self.env.user:
                sale_binding_model = sale_binding_model.sudo(user)

            if not import_end_time:
                # We minus two minutes to now time
                import_end_time = datetime.strptime(datetime.today().strftime('%Y-%m-%d %H:%M:%S'), '%Y-%m-%d %H:%M:%S') - timedelta(minutes=2)
            if not import_start_time:
                if backend.import_sales_from_date:
                    import_start_time = datetime.strptime(backend.import_updated_sales_from_date, '%Y-%m-%d %H:%M:%S')
                else:
                    import_start_time = import_end_time

            sale_binding_model.import_batch(backend, filters={'update_start':import_start_time.isoformat(),
                                                              'update_end':import_end_time.isoformat(),
                                                              'update_sales_flag':True})
            if update_import_date:
                backend.write({'import_updated_sales_from_date':import_end_time})

    @api.model
    def _update_product_stock_qty_prices(self):
        for backend in self:
            user = backend.warehouse_id.company_id.user_tech_id
            if not user:
                user = self.env['res.users'].browse(self.env.uid)
            product_binding_model = self.env['amazon.product.product']
            if user != self.env.user:
                product_binding_model = product_binding_model.sudo(user)
            # We are going to import the initial prices, fees and prices changes
            product_binding_model.import_record_details(backend)
            # We are going to export the stock and prices changes
            product_binding_model.export_batch(backend)

    @api.multi
    def _fix_amazon_data(self):
        if self:
            backend = self[0]
            with backend.work_on(self._name) as work:
                fix_data = work.component(usage='amazon.fix.data')
                fix_data.run()

        return True

    @api.multi
    def _get_price_changes(self):
        for backend in self:
            user = backend.warehouse_id.company_id.user_tech_id
            if not user:
                user = self.env['res.users'].browse(self.env.uid)
            product_binding_model = self.env['amazon.product.product']
            if user != self.env.user:
                product_binding_model = product_binding_model.sudo(user)
            # We are going to import the initial prices, fees and prices changes
            product_binding_model.import_changesex_prices_record(backend)

    @api.multi
    def _throw_feeds(self):
        for backend in self:
            _logger.info('Connector-amazon [%s] log: Throw feeds init with %s backend' % (inspect.stack()[0][3], backend.name))
            user = backend.warehouse_id.company_id.user_tech_id
            if not user:
                user = self.env['res.users'].browse(self.env.uid)

            feeds_to_throw = self.env['amazon.feed.tothrow'].search([('backend_id', '=', backend.id),
                                                                     ('launched', '=', False),
                                                                     ('type', 'in', ['Update_stock', 'Update_stock_price', 'Add_products_csv'])])

            data_update_stock = {}
            data_update_stock_price = {}
            add_products_to_inventory = {}

            # In the next loop we are going to construct the structure to throw the feed, we are going to filter the duplicate data per market and sku
            for feed_to_throw in feeds_to_throw:
                element = ast.literal_eval(feed_to_throw.data)
                element['create_date'] = feed_to_throw.create_date

                if feed_to_throw.type == 'Update_stock':
                    # If there isn't the markeplace added we add this
                    if not data_update_stock.get(element['id_mws']):
                        data_update_stock[element['id_mws']] = {}

                    # We check if the sku is added on this marketplace
                    if not data_update_stock[element['id_mws']].get(element['sku']):
                        data_update_stock[element['id_mws']][element['sku']] = element
                    elif data_update_stock[element['id_mws']][element['sku']]['create_date'] < element['create_date']:
                        data_update_stock[element['id_mws']].pop(element['sku'])
                        data_update_stock[element['id_mws']][element['sku']] = element

                elif feed_to_throw.type == 'Update_stock_price':
                    # If there isn't the markeplace added we add this
                    if not data_update_stock_price.get(element['id_mws']):
                        data_update_stock_price[element['id_mws']] = {}

                    # We check if the sku is added on this marketplace
                    if not data_update_stock_price[element['id_mws']].get(element['sku']):
                        data_update_stock_price[element['id_mws']][element['sku']] = element
                    elif data_update_stock_price[element['id_mws']][element['sku']]['create_date'] < element['create_date']:
                        data_update_stock_price[element['id_mws']].pop(element['sku'])
                        data_update_stock_price[element['id_mws']][element['sku']] = element
                elif feed_to_throw.type == 'Add_products_csv':
                    # If there isn't the markeplace added we add this
                    if not add_products_to_inventory.get(element['id_mws']):
                        add_products_to_inventory[element['id_mws']] = {}

                    # We check if the sku is added on this marketplace
                    if not add_products_to_inventory[element['id_mws']].get(element['sku']):
                        add_products_to_inventory[element['id_mws']][element['sku']] = element
                    elif add_products_to_inventory[element['id_mws']][element['sku']]['create_date'] < element['create_date']:
                        add_products_to_inventory[element['id_mws']].pop(element['sku'])
                        add_products_to_inventory[element['id_mws']][element['sku']] = element

            _logger.info('Connector-amazon [%s] log: Update throw feeds to launched with %s backend' % (inspect.stack()[0][3], backend.name))
            feeds_to_throw.write({'launched':True, 'date_launched':datetime.now().isoformat(sep=' ')})
            _logger.info('Connector-amazon [%s] log: Finish update throw feeds to launched with %s backend' % (inspect.stack()[0][3], backend.name))

            with backend.work_on(self._name) as work:
                if data_update_stock:
                    exporter_stock = work.component(model_name='amazon.product.product', usage='amazon.product.stock.export')
                    exporter_stock.run(data_update_stock)

                if data_update_stock_price:
                    exporter_stock_price = work.component(model_name='amazon.product.product', usage='amazon.product.stock.price.export')
                    exporter_stock_price.run([data_update_stock_price])

                if add_products_to_inventory:
                    exporter_product = work.component(model_name='amazon.product.product', usage='amazon.product.export')
                    ids = exporter_product.run([add_products_to_inventory])
                    if not ids:
                        raise UserError(_('An error has been produced'))

                    feed = self.env['amazon.feed']
                    user = backend.warehouse_id.company_id.user_tech_id
                    if not user:
                        user = self.env['res.users'].browse(self.env.uid)
                    if user != self.env.user:
                        feed = feed.sudo(user)
                    delayable = feed.with_delay(priority=1, eta=datetime.now() + timedelta(minutes=15))
                    filters = {'method':'analize_product_exports', 'feed_ids':ids, 'products':add_products_to_inventory, 'backend':backend}
                    delayable.import_batch(backend, filters=filters)

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
    def _scheduler_import_export_product_product(self, domain=None):
        self._amazon_backend('_import_export_product_product', domain=domain)

    @api.model
    def _scheduler_update_product_prices_stock_qty(self, domain=None):
        self._amazon_backend('_update_product_stock_qty_prices', domain=domain)

    @api.model
    def _scheduler_connector_amazon_fix_data(self, domain=None):
        self._amazon_backend('_fix_amazon_data', domain=domain)

    @api.model
    def _scheduler_get_price_changes(self, domain=None):
        self._amazon_backend('_get_price_changes', domain=domain)

    @api.model
    def _scheduler_throw_feeds(self, domain=None):
        self._amazon_backend('_throw_feeds', domain=domain)
