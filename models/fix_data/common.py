# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import logging
import odoo

from datetime import datetime, timedelta
from odoo import models, api, fields, tools
from odoo.addons.queue_job.job import job
from odoo.addons.queue_job.job import FAILED, STARTED, ENQUEUED

AMAZON_SAVE_OLD_FEED = 10000
AMAZON_SAVE_OLD_FEED_TO_THROW = 50000
AMAZON_FEED_TO_THROW_DELETE_PER_TIME = 5000000
AMAZON_REQUEST_DATE_DELETE_PER_TIME = 5000000
AMAZON_SAVE_OLD_SQS_MESSAGES = 10000
AMAZON_DELETE_JOBS_OLD_THAN = 7  # It is on days
AMAZON_SAVE_OLD_HISTORIC_OFFERS = 3
AMAZON_HISTORIC_OFFERS_DELETE_PER_TIME = 500
AMAZON_MAX_DELETE_JOBS = 5000000
AMAZON_MAX_NUMBER_DUPLICATE_MESSAGES = 3000

_logger = logging.getLogger(__name__)


class AmazonFixData(models.Model):
    _name = 'amazon.fix.data'
    _inherit = 'amazon.binding'
    _description = 'Amazon Fix Data'

    @api.multi
    def batch_unlink(self, records):
        if records:
            with api.Environment.manage():
                with odoo.registry(
                        records.env.cr.dbname).cursor() as new_cr:
                    new_env = api.Environment(new_cr, records.env.uid,
                                              records.env.context)
                    try:
                        while records:
                            batch_delete = records[0:1000]
                            records -= batch_delete
                            # do not attach new env to self because it may be
                            # huge, and the cache is cleaned after each unlink
                            # so we do not want to much record is the env in
                            # which we call unlink because odoo would prefetch
                            # fields, cleared right after.
                            batch_delete.with_env(new_env).unlink()
                            new_env.cr.commit()
                    except Exception as e:
                        _logger.exception(
                            "Connector amazon fix data failed to delete Ms : %s" % (records._name, str(e)))

    @api.multi
    def batch_requeue(self, records):
        if records:
            with api.Environment.manage():
                with odoo.registry(
                        records.env.cr.dbname).cursor() as new_cr:
                    new_env = api.Environment(new_cr, records.env.uid,
                                              records.env.context)
                    try:
                        while records:
                            batch_requeue = records[0:1000]
                            records -= batch_requeue
                            # do not attach new env to self because it may be
                            # huge, and the cache is cleaned after each unlink
                            # so we do not want to much record is the env in
                            # which we call unlink because odoo would prefetch
                            # fields, cleared right after.
                            batch_requeue.requeue()
                            new_env.cr.commit()
                    except Exception as e:
                        _logger.exception(
                            "Connector amazon fix data failed requeue jobs: %s" % (records._name, str(e.message)))

    @job(default_channel='root.amazon')
    @api.model
    def run_delayed_jobs(self, backend):
        delayable = self.with_delay(priority=7, eta=datetime.now())
        delayable.description = '%s.%s' % (self._name, 'clean_duplicate_amazon_products()')
        delayable.clean_duplicate_amazon_products()

        delayable2 = self.with_delay(priority=7, eta=datetime.now())
        delayable2.description = '%s.%s' % (self._name, 'throw_concurrent_jobs()')
        delayable2.throw_concurrent_jobs()

        delayable3 = self.with_delay(priority=7, eta=datetime.now())
        delayable3.description = '%s.%s' % (self._name, 'delete_old_feeds()')
        delayable3.delete_old_feeds()

        delayable4 = self.with_delay(priority=7, eta=datetime.now())
        delayable4.description = '%s.%s' % (self._name, 'delete_old_sqs_messages()')
        delayable4.delete_old_sqs_messages()

        delayable5 = self.with_delay(priority=7, eta=datetime.now())
        delayable5.description = '%s.%s' % (self._name, 'clean_sqs_messages()')
        delayable5.clean_sqs_messages()

        delayable7 = self.with_delay(priority=7, eta=datetime.now())
        delayable7.description = '%s.%s' % (self._name, 'clean_old_quota_control_data()')
        delayable7.clean_old_quota_control_data()

        delayable8 = self.with_delay(priority=7, eta=datetime.now())
        count = self.env['queue.job'].search_count([('channel', 'ilike', 'root.amazon'),
                                                    ('name', 'ilike', 'set_pending_hang_jobs'),
                                                    ('state', 'in', ('pending', 'started', 'enqueued')), ])
        if count == 0:
            delayable8.description = '%s.%s' % (self._name, 'set_pending_hang_jobs()')
            delayable8.set_pending_hang_jobs()

        delayable9 = self.with_delay(priority=7, eta=datetime.now())
        delayable9.description = '%s.%s' % (self._name, 'get_service_level_order_or_partner_name()')
        delayable9.get_service_level_order_or_partner_name()

        delayable10 = self.with_delay(priority=7, eta=datetime.now())
        count = self.env['queue.job'].search_count([('channel', 'ilike', 'root.amazon'),
                                                    ('name', 'ilike', 'delete_old_done_failed_jobs'),
                                                    ('state', 'in', ('pending', 'started', 'enqueued')), ])
        if count == 0:
            delayable10.description = '%s.%s' % (self._name, 'delete_old_done_failed_jobs()')
            delayable10.delete_old_done_failed_jobs()

    @job(default_channel='root.amazon')
    @api.model
    def clean_sqs_messages(self):
        """
        Clean duplicate sqs messages
        :return:
        """
        sqs_message_env = self.env['amazon.config.sqs.message']
        sqs_message_env._cr.execute(""" SELECT 
                                            id, id_message
                                        FROM 
                                            amazon_config_sqs_message
                                        WHERE
                                            id_message in
                                                (SELECT 
                                                    id_message
                                                FROM 
                                                    amazon_config_sqs_message
                                                WHERE 
                                                    processed=False
                                                GROUP BY id_message
                                                HAVING COUNT(id_message)>1)
                                        ORDER BY id_message
                                                """)

        message_ids = sqs_message_env._cr.dictfetchall()
        message = ''
        list_ids = []
        i = 0
        for id_message in message_ids:
            if message == id_message['id_message']:
                list_ids.append(id_message['id'])
                i += 1
                if i > AMAZON_MAX_NUMBER_DUPLICATE_MESSAGES:
                    break

            message = id_message['id_message']

        if list_ids:
            sqs_message_env.browse(list_ids).unlink()

    @job(default_channel='root.amazon')
    @api.model
    def delete_old_done_failed_jobs(self):
        time_from = (datetime.now() - timedelta(days=AMAZON_DELETE_JOBS_OLD_THAN)).strftime("%Y-%m-%d %H:%M:%S")
        jobs = self.env['queue.job'].search([('channel', 'ilike', 'root.amazon'),
                                             ('date_created', '<', time_from),
                                             '|',
                                             ('state', '=', 'done'),
                                             ('state', '=', 'failed')], limit=AMAZON_MAX_DELETE_JOBS)

        _logger.info("Number of jobs to delete: %s" % str(len(jobs)))

        self.batch_unlink(jobs)

    @job(default_channel='root.amazon')
    @api.model
    def set_pending_hang_jobs(self):
        time_to_requeue = datetime.now() - timedelta(hours=2)
        jobs = self.env['queue.job'].search(['&',
                                             ('channel', 'like', 'root.amazon'),
                                             '|',
                                             ('date_started', '>', time_to_requeue.isoformat(sep=' ')),
                                             ('date_enqueued', '>', time_to_requeue.isoformat(sep=' ')),
                                             '|',
                                             ('state', '=', STARTED),
                                             ('state', '=', ENQUEUED), ])

        self.batch_requeue(jobs)

    @job(default_channel='root.amazon')
    @api.model
    def clean_old_quota_control_data(self):
        time_to_requeue = datetime.now() - timedelta(hours=1)
        requests = self.env['amazon.control.date.request'].search([('create_date', '<', time_to_requeue.isoformat(sep=' '))], )

        self.batch_unlink(requests)

    @job(default_channel='root.amazon')
    @api.model
    def delete_old_feeds(self):
        count_feeds = self.env['amazon.feed'].search_count([])

        if count_feeds > AMAZON_SAVE_OLD_FEED:
            self.env['amazon.feed'].search([], order='create_date asc', limit=count_feeds - AMAZON_SAVE_OLD_FEED).unlink()

        count_feeds_to_throw = self.env['amazon.feed.tothrow'].search_count([('launched', '=', True)])

        feed_to_delete = count_feeds_to_throw - AMAZON_SAVE_OLD_FEED_TO_THROW
        if feed_to_delete > 0:
            limit_feeds = 1
            if feed_to_delete > AMAZON_FEED_TO_THROW_DELETE_PER_TIME:
                limit_feeds = AMAZON_FEED_TO_THROW_DELETE_PER_TIME
            else:
                limit_feeds = feed_to_delete

            self.env['amazon.feed.tothrow'].search([('launched', '=', True)],
                                                   order='create_date asc',
                                                   limit=limit_feeds).unlink()

    @job(default_channel='root.amazon')
    @api.model
    def delete_old_sqs_messages(self):
        count_messages = self.env['amazon.config.sqs.message'].search_count([('processed', '=', True)])

        # if count_messages > AMAZON_SAVE_OLD_SQS_MESSAGES:
        messages = self.env['amazon.config.sqs.message'].search([('processed', '=', True)], order='create_date asc', )

        self.batch_unlink(messages)

    @job(default_channel='root.amazon')
    @api.model
    def delete_old_offers(self):
        amazon_historic_offer_env = self.env['amazon.historic.product.offer']

        # Delete offer of the old structure
        sql = """SELECT 
                     id 
                 FROM 
                     amazon_product_offer 
                 WHERE 
                     product_detail_id is not null"""

        amazon_historic_offer_env._cr.execute(sql)
        offer_ids = amazon_historic_offer_env._cr.dictfetchall()
        list_offer_ids = []
        for offer in offer_ids:
            # Check if delete the offer
            list_offer_ids.append(offer['id'])

        if list_offer_ids:
            amazon_historic_offer_env.browse(list_offer_ids).unlink()
            return

        # Recover historic offers of products have more than tree offers to delete old od these
        amazon_historic_offer_env._cr.execute(""" SELECT
                                            id
                                        FROM
                                            amazon_historic_product_offer 
                                        WHERE product_detail_id IN 
                                            (SELECT 
                                                product_detail_id 
                                             FROM 
                                                amazon_historic_product_offer 
                                             GROUP BY 
                                                product_detail_id HAVING count(product_detail_id)>%s limit %s)
                                        ORDER BY 
                                            product_detail_id, offer_date DESC
                                                """ % (str(AMAZON_SAVE_OLD_HISTORIC_OFFERS), str(AMAZON_HISTORIC_OFFERS_DELETE_PER_TIME)))

        historic_offer_ids = amazon_historic_offer_env._cr.dictfetchall()
        id_hist = ''
        i = 0
        list_historic_ids = []
        for historic_offer in historic_offer_ids:

            # If there is a change or it is the first time
            if id_hist != historic_offer['id']:
                id_hist = historic_offer['id']
                i = 0

            # Check if delete the offer
            if i > AMAZON_SAVE_OLD_HISTORIC_OFFERS:
                list_historic_ids.append(historic_offer['id'])
            i += 1
            if list_historic_ids > AMAZON_HISTORIC_OFFERS_DELETE_PER_TIME:
                break
        if list_historic_ids:
            amazon_historic_offer_env.browse(list_historic_ids).unlink()

    @job(default_channel='root.amazon')
    @api.model
    def throw_concurrent_jobs(self):
        """
        Get failed jobs of amazon that have an exception for concurrent and throw this again
        :return:
        """
        jobs = self.env['queue.job'].search(['&', ('state', '=', FAILED), ('channel', '=', 'root.amazon'),
                                             '|',
                                             ('exc_info', 'ilike',
                                              'InternalError: current transaction is aborted, commands ignored until end of transaction block'),
                                             ('exc_info', 'ilike',
                                              'TransactionRollbackError: could not serialize access due to concurrent update'),
                                             ])

        self.batch_requeue(jobs)

    @job(default_channel='root.amazon')
    @api.model
    def clean_duplicate_jobs(self):
        """
                Clean duplicate jobs
                :return:
                """
        queue_job_env = self.env['queue.job']
        queue_job_env._cr.execute(""" SELECT 
                                                    id, func_string
                                                FROM 
                                                    queue_job
                                                WHERE
                                                    func_string in
                                                        (SELECT 
                                                            func_string
                                                        FROM 
                                                            queue_job
                                                        WHERE 
                                                            channel = 'root.amazon'
                                                            and state in ('pending', 'started', 'enqueued')
                                                        GROUP BY func_string
                                                        HAVING COUNT(func_string)>1)
                                                AND state in ('pending', 'started', 'enqueued')
                                                ORDER BY func_string
                                                        """)

        jobs_ids = queue_job_env._cr.dictfetchall()
        task = ''
        list_ids = []
        i = 0
        for id_job in jobs_ids:
            if task == id_job['func_string']:
                list_ids.append(id_job['id'])
                i += 1
                if i > AMAZON_MAX_DELETE_JOBS:
                    break

            task = id_job['func_string']

        jobs = queue_job_env.browse(list_ids)
        self.batch_unlink(jobs)

    @job(default_channel='root.amazon')
    @api.model
    def get_service_level_order_or_partner_name(self):
        orders_count = 0
        amazon_sales = []

        while orders_count < 150:
            orders = self.env['amazon.sale.order'].search([('shipment_service_level_category', '=', False),
                                                           ('order_status_id.name', '=', 'Unshipped')], limit=50) \
                     or \
                     self.env['amazon.sale.order'].search(
                         [('amazon_partner_id.name', '=', False)], limit=50) \
                     or \
                     self.env['amazon.sale.order'].search(
                         [('shipment_service_level_category', '=', False)], limit=50)

            orders_count += 50

            if orders:
                order_ids = orders.mapped('id_amazon_order')
                importer_sale_order = self.work.component(model_name='amazon.sale.order', usage='amazon.sale.data.import')
                json_orders = importer_sale_order.get_orders(ids=[order_ids])
                if json_orders and not isinstance(json_orders, list):
                    json_orders = [json_orders]
                amazon_sales.extend(json_orders)

            if len(orders) < 50:
                break

        for amazon_sale_dict in amazon_sales:
            sale = self.env['amazon.sale.order'].search([('id_amazon_order', '=', amazon_sale_dict['order_id'])])
            if not sale.amazon_partner_id.name:
                importer_partner = self.work.component(model_name='amazon.res.partner', usage='record.importer')
                importer_partner.amazon_record = amazon_sale_dict['partner']
                importer_partner.run(external_id=amazon_sale_dict['partner']['email'])

            vals = {'shipment_service_level_category':amazon_sale_dict['shipment_service_level_category']}
            sale.write(vals)

    @job(default_channel='root.amazon')
    @api.model
    def clean_duplicate_amazon_products(self):
        """
            Clean duplicate jobs
            :return:
        """
        duplicate_products = self.env['amazon.duplicate.product.backend.report'].search([])
        for duplicate in duplicate_products:
            if not duplicate.amazon_product_id.product_product_market_ids:
                duplicate.amazon_product_id.unlink()


class AmazonDuplicateProductBackendReport(models.Model):
    _name = "amazon.duplicate.product.backend.report"
    _description = "Amazon duplicate product on several backend"
    _auto = False

    amazon_product_id = fields.Many2one('amazon.product.product')
    sku = fields.Char('Sku')
    asin = fields.Char('ASIN')
    backend_id = fields.Many2one('amazon.backend')
    amazon_qty = fields.Char('amazon_qty')

    @api.model_cr
    def init(self):
        tools.drop_view_if_exists(self._cr, 'amazon_duplicate_product_backend_report')
        self._cr.execute("""
            create or replace view amazon_duplicate_product_backend_report as (
                select 
                    id,
                    id as amazon_product_id,
                    sku, 
                    asin,
                    backend_id,
                    amazon_qty
                from 
                    amazon_product_product 
                where sku in
                    (select 
                        sku 
                     from 
                        amazon_product_product 
                     group by 
                        sku 
                     having count(sku)>1) 
                order by 
                    sku
            )""")