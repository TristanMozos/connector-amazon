# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import datetime
import logging
import inspect
from datetime import datetime, timedelta

from odoo.addons.component.core import Component
from odoo.addons.queue_job.job import FAILED, STARTED, ENQUEUED, DONE

AMAZON_SAVE_OLD_FEED = 10000
AMAZON_SAVE_OLD_FEED_TO_THROW = 50000
AMAZON_SAVE_OLD_SQS_MESSAGES = 10000
AMAZON_SAVE_OLD_HISTORIC_OFFERS = 10

_logger = logging.getLogger(__name__)


class ProductFixData(Component):
    _name = 'amazon.fix.data.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.backend']
    _usage = 'amazon.fix.data'

    def _set_pending_hang_jobs(self):
        _logger.info('Connector_amazon [%s] log: Set the Amazon hang jobs to pending' % inspect.stack()[0][3])
        time_to_requeue = datetime.now() - timedelta(hours=2)
        jobs = self.env['queue.job'].search(['&',
                                             ('channel', 'like', 'root.amazon'),
                                             '|',
                                             ('date_started', '>', time_to_requeue.isoformat(sep=' ')),
                                             ('date_enqueued', '>', time_to_requeue.isoformat(sep=' ')),
                                             '|',
                                             ('state', '=', STARTED),
                                             ('state', '=', ENQUEUED), ])

        for job in jobs:
            job.requeue()

        _logger.info('Connector_amazon [%s] log: Finish set the Amazon hang jobs to pending' % inspect.stack()[0][3])

    def _clean_old_quota_control_data(self):
        _logger.info('Connector_amazon [%s] log: Clean Amazon old quota control' % inspect.stack()[0][3])
        time_to_requeue = datetime.now() - timedelta(days=1)
        self.env['amazon.control.date.request'].search([('request_date', '<', time_to_requeue.isoformat(sep=' '))]).unlink()
        _logger.info('Connector_amazon [%s] log: Finish clean Amazon old quota control' % inspect.stack()[0][3])

    def _delete_old_feeds(self):
        _logger.info('Connector_amazon [%s] log: Delete Amazon old feeds' % inspect.stack()[0][3])
        count_feeds = self.env['amazon.feed'].search_count([])

        if count_feeds > AMAZON_SAVE_OLD_FEED:
            self.env['amazon.feed'].search([], order='create_date asc', limit=count_feeds - AMAZON_SAVE_OLD_FEED).unlink()

        count_feeds_to_throw = self.env['amazon.feed.tothrow'].search_count([])

        if count_feeds_to_throw > AMAZON_SAVE_OLD_FEED_TO_THROW:
            self.env['amazon.feed.tothrow'].search([], order='create_date asc', limit=count_feeds_to_throw - AMAZON_SAVE_OLD_FEED).unlink()

        _logger.info('Connector_amazon [%s] log: Finish delete Amazon old feeds' % inspect.stack()[0][3])

    def _delete_old_sqs_messages(self):
        _logger.info('Connector_amazon [%s] log: Delete Amazon old SQS messages' % inspect.stack()[0][3])
        count_messages = self.env['amazon.config.sqs.message'].search_count([('processed', '=', True)])

        if count_messages > AMAZON_SAVE_OLD_SQS_MESSAGES:
            self.env['amazon.config.sqs.message'].search([('processed', '=', True)],
                                                         order='create_date asc',
                                                         limit=count_messages - AMAZON_SAVE_OLD_SQS_MESSAGES).unlink()

        _logger.info('Connector_amazon [%s] log: Finish delete Amazon old SQS messages' % inspect.stack()[0][3])

    def _delete_old_offers(self):
        _logger.info('Connector_amazon [%s] log: Delete Amazon old offers' % inspect.stack()[0][3])
        # TODO the next code has a huge sql queries that hang the machine where the code runs
        '''
        product_details = self.env['amazon.product.product.detail'].search([])
        rcs = None
        for product_detail in product_details:
            count_historics = len(product_detail.historic_offer_ids)
            if count_historics > AMAZON_SAVE_OLD_HISTORIC_OFFERS:
                if rcs:
                    rcs |= product_detail.historic_offer_ids.sorted(key=lambda r:r.offer_date)[count_historics - AMAZON_SAVE_OLD_HISTORIC_OFFERS:]
                else:
                    rcs = product_detail.historic_offer_ids.sorted(key=lambda r:r.offer_date)[count_historics - AMAZON_SAVE_OLD_HISTORIC_OFFERS:]

        rcs.unlink()
        '''
        _logger.info('Connector_amazon [%s] log: Finish delete Amazon old offers' % inspect.stack()[0][3])

    def _throw_concurrent_jobs(self):
        """
        Get failed jobs of amazon that have an exception for concurrent and throw this again
        :return:
        """
        _logger.info('Connector_amazon [%s] log: Throw Amazon concurrent jobs' % inspect.stack()[0][3])
        jobs = self.env['queue.job'].search(['&', ('state', '=', FAILED),
                                             '|',
                                             ('exc_info', 'ilike',
                                              'InternalError: current transaction is aborted, commands ignored until end of transaction block'),
                                             ('exc_info', 'ilike',
                                              'TransactionRollbackError: could not serialize access due to concurrent update'),
                                             '|',
                                             ('job_function_id.name', 'like', 'amazon.sale.order'),
                                             ('job_function_id.name', 'like', 'amazon.product.product'), ])

        for job in jobs:
            job.requeue()

        _logger.info('Connector_amazon [%s] log: Finish throw Amazon concurrent jobs' % inspect.stack()[0][3])

    def _clean_duplicate_jobs(self):
        """
        Clean duplicate jobs
        :return:
        """
        _logger.info('Connector_amazon [%s] log: Clean Amazon duplicate jobs' % inspect.stack()[0][3])
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
                                                    HAVING COUNT(func_string)>1
                                                    ORDER BY func_string)
                                                    AND state in ('pending', 'started', 'enqueued')
                                                        """)

        jobs_ids = queue_job_env._cr.dictfetchall()
        task = ''
        for id_job in jobs_ids:
            if task == id_job['func_string']:
                queue_job_env.browse(id_job['id']).write({'state':DONE,
                                                          'exc_info':None,
                                                          'date_done':datetime.now(),
                                                          'result':'Duplicate task at the same time'})

            task = id_job['func_string']

        _logger.info('Connector_amazon [%s] log: Finish clean Amazon duplicate jobs' % inspect.stack()[0][3])

    def _get_service_level_order_or_partner_name(self):
        _logger.info('Connector_amazon [%s] log: Start get service level of Amazon orders' % inspect.stack()[0][3])

        orders_count = 0
        amazon_sales = []

        while orders_count < 150:
            orders = self.env['amazon.sale.order'].search([('shipment_service_level_category', '=', False),
                                                           ('order_status_id.name', '=', 'Unshipped'),
                                                           ('backend_id', '=', self.backend_record.id)], limit=50) \
                     or \
                     self.env['amazon.sale.order'].search(
                         [('amazon_partner_id.name', '=', False),
                          ('backend_id', '=', self.backend_record.id)], limit=50) \
                     or \
                     self.env['amazon.sale.order'].search(
                         [('shipment_service_level_category', '=', False),
                          ('backend_id', '=', self.backend_record.id)], limit=50)

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

        _logger.info('Connector_amazon [%s] log: Finish get service level of Amazon orders' % inspect.stack()[0][3])

    def run(self):

        try:
            self._clean_duplicate_jobs()
        except Exception as e:
            _logger.info('Connector_amazon log: exception executing _clean_duplicate_jobs [%s]' % e.message)
        try:
            self._throw_concurrent_jobs()
        except Exception as e:
            _logger.info('Connector_amazon log: exception executing _throw_concurrent_jobs [%s]' % e.message)
        try:
            self._delete_old_feeds()
        except Exception as e:
            _logger.info('Connector_amazon log: exception executing _delete_old_feeds [%s]' % e.message)
        try:
            self._delete_old_sqs_messages()
        except Exception as e:
            _logger.info('Connector_amazon log: exception executing _delete_old_sqs_messages [%s]' % e.message)
        try:
            self._delete_old_offers()
        except Exception as e:
            _logger.info('Connector_amazon log: exception executing _delete_old_offers [%s]' % e.message)
        try:
            self._clean_old_quota_control_data()
        except Exception as e:
            _logger.info('Connector_amazon log: exception executing _clean_old_quota_control_data [%s]' % e.message)
        try:
            self._set_pending_hang_jobs()
        except Exception as e:
            _logger.info('Connector_amazon log: exception executing _set_pending_hang_jobs [%s]' % e.message)
        try:
            self._get_service_level_order_or_partner_name()
        except Exception as e:
            _logger.info('Connector_amazon log: exception executing _get_service_level_order [%s]' % e.message)
