# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import models, fields, api
from odoo.addons.component.core import Component
from odoo.addons.queue_job.job import job

_logger = logging.getLogger(__name__)

FEED_TYPES = {'_POST_PRODUCT_DATA_':'_POST_PRODUCT_DATA_',
              '_POST_INVENTORY_AVAILABILITY_DATA_':'_POST_INVENTORY_AVAILABILITY_DATA_',
              '_POST_PRODUCT_OVERRIDES_DATA_':'_POST_PRODUCT_OVERRIDES_DATA_',
              'Update_stock':'_POST_PRODUCT_PRICING_DATA_',
              '_POST_PRODUCT_IMAGE_DATA_':'_POST_PRODUCT_IMAGE_DATA_',
              '_POST_PRODUCT_RELATIONSHIP_DATA_':'_POST_PRODUCT_RELATIONSHIP_DATA_',
              'Add_products_csv':'_POST_FLAT_FILE_INVLOADER_DATA_',
              '_POST_FLAT_FILE_LISTINGS_DATA_':'_POST_FLAT_FILE_LISTINGS_DATA_',
              'Update_stock_price':'_POST_FLAT_FILE_PRICEANDQUANTITYONLY_UPDATE_DATA_',
              }

FEED_STATUS = {'_AWAITING_ASYNCHRONOUS_REPLY_':'_AWAITING_ASYNCHRONOUS_REPLY_',
               '_CANCELLED_':'_CANCELLED_',
               '_DONE_':'_DONE_',
               '_IN_PROGRESS_':'_IN_PROGRESS_',
               '_IN_SAFETY_NET_':'_IN_SAFETY_NET_',
               '_SUBMITTED_':'_SUBMITTED_',
               '_UNCONFIRMED_':'_UNCONFIRMED_', }


class AmazonFeed(models.Model):
    _name = "amazon.feed"
    _inherit = 'amazon.binding'
    _description = 'Amazon Feed'

    backend_id = fields.Many2one('amazon.backend', required=True)
    id_feed_submision = fields.Char(required=True)
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


class AmazonFeedAdapter(Component):
    _name = 'amazon.feed.adapter'
    _inherit = 'amazon.adapter'
    _apply_on = 'amazon.feed'

    @api.multi
    def submit_feed(self, feed_name, arguments):
        return self._call(method=feed_name, arguments=arguments)
