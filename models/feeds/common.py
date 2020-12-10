# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import models, fields, api
from odoo.addons.component.core import Component
from odoo.addons.queue_job.job import job

_logger = logging.getLogger(__name__)

# TODO delete deprecated types
FEED_TYPES = {'Update_stock':'_POST_INVENTORY_AVAILABILITY_DATA_', # Deprecated
              'Add_products_csv':'_POST_FLAT_FILE_INVLOADER_DATA_', # Deprecated
              'Update_stock_price':'_POST_FLAT_FILE_PRICEANDQUANTITYONLY_UPDATE_DATA_', # Deprecated
              'Confirm_shipment':'_POST_FLAT_FILE_FULFILLMENT_DATA_', # Deprecated
              'Migrate_backend':'Migrate backend',
              '_POST_INVENTORY_AVAILABILITY_DATA_':'Update stock',
              '_POST_PRODUCT_PRICING_DATA_': 'Update price',
              '_POST_FLAT_FILE_PRICEANDQUANTITYONLY_UPDATE_DATA_': 'Update stock price',
              '_POST_FLAT_FILE_INVLOADER_DATA_':'Add products csv',
              '_POST_PRODUCT_DATA_DELETE_': 'Delete inventory products',
              '_POST_FLAT_FILE_FULFILLMENT_DATA_':'Confirm shipment',
              '_POST_PRODUCT_DATA_':'Create/delete product',
              '_POST_PRODUCT_OVERRIDES_DATA_':'_POST_PRODUCT_OVERRIDES_DATA_',
              '_POST_PRODUCT_IMAGE_DATA_':'_POST_PRODUCT_IMAGE_DATA_',
              '_POST_PRODUCT_RELATIONSHIP_DATA_':'_POST_PRODUCT_RELATIONSHIP_DATA_',
              '_POST_FLAT_FILE_LISTINGS_DATA_':'_POST_FLAT_FILE_LISTINGS_DATA_',
              }

FEED_STATUS = {'_AWAITING_ASYNCHRONOUS_REPLY_':'Awaiting asynchronous reply',
               '_CANCELLED_':'Cancelled',
               '_DONE_':'Done',
               '_IN_PROGRESS_':'In progress',
               '_IN_SAFETY_NET_':'In safety net',
               '_SUBMITTED_':'Submitted',
               '_UNCONFIRMED_':'Unconfirmed', }


class AmazonFeed(models.Model):
    _name = "amazon.feed"
    _inherit = 'amazon.binding'
    _description = 'Amazon Feed'

    backend_id = fields.Many2one('amazon.backend', required=True)
    id_feed_submision = fields.Char(required=True)
    feed_result_id = fields.Many2one('amazon.feed.result', 'Result of feed')
    type = fields.Selection('get_feed_types',
                            string='Type of feed',
                            required=True)
    submitted_date = fields.Datetime()

    feed_processing_status = fields.Selection('get_feed_status',
                                              string='Processing feed status')

    started_processing_date = fields.Datetime()

    completed_processing_date = fields.Datetime()

    params = fields.Char('Params of the feed submited')

    xml_csv = fields.Char('File (xml/csv) submitted on feed')

    def get_feed_types(self):
        lst = []
        for key, value in FEED_TYPES.iteritems():
            lst.append((key, value))
        return lst

    def get_feed_status(self):
        lst = []
        for key, value in FEED_STATUS.iteritems():
            lst.append((key, value))
        return lst

    @job(default_channel='root.amazon')
    @api.model
    def export_batch(self, backend, filters=None):
        _super = super(AmazonFeed, self)
        return _super.export_batch(backend, filters=filters)

    @job(default_channel='root.amazon')
    @api.model
    def import_record(self, backend, external_id):
        exception = None
        with backend.work_on(self._name) as work:
            try:
                importer = work.component(usage='record.importer')
                return importer.run(external_id)
            except Exception as e:
                exception = e
        if exception:
            raise exception


class AmazonFeedToThrow(models.Model):
    _name = 'amazon.feed.tothrow'

    backend_id = fields.Many2one('amazon.backend', required=True)
    type = fields.Selection('get_feed_types', string='Type of feed', required=True)
    model = fields.Char('Model on the change will do', required=True)
    identificator = fields.Char('Identificator of the object on the change will do', required=True)
    marketplace_id = fields.Many2one('amazon.config.marketplace', "Marketplace")
    data = fields.Char('Data to send to csv or xml', required=True)
    launched = fields.Boolean('Define if the data has been launched or not', default=False)
    date_launched = fields.Datetime('When the data has been launched if it is informed')

    def get_feed_types(self):
        lst = []
        for key, value in FEED_TYPES.iteritems():
            lst.append((key, value))
        return lst

class AmazonFeedResult(models.Model):
    _name = 'amazon.feed.result'

    feed_id = fields.Many2one('amazon.feed', required=True)
    messages_processed = fields.Integer('Messages processed')
    messages_successful = fields.Integer('Messages successful')
    messages_werror = fields.Integer('Messages with error')
    messages_wwarning = fields.Integer('Messages with warning')
    message = fields.Char()



class AmazonFeedAdapter(Component):
    _name = 'amazon.feed.adapter'
    _inherit = 'amazon.adapter'
    _apply_on = 'amazon.feed'

    @api.multi
    def submit_feed(self, feed_name, arguments):
        return self._call(method=feed_name, arguments=arguments)

    @api.multi
    def get_feed(self, feed_name, arguments):
        return self._call(method=feed_name, arguments=arguments)
