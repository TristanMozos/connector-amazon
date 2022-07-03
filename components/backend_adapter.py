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
# This project is based on connector-magneto, developed by Camptocamp SA
##############################################################################

from io import StringIO
import ast
import logging
import re
import odoo

from datetime import datetime, timedelta

import dateutil.parser
import unicodecsv
from lxml import etree
from odoo import api, registry
from odoo.addons.component.core import AbstractComponent
from odoo.addons.queue_job.exception import FailedJobError, RetryableJobError
from odoo.fields import Datetime, Date

# from ..models.config.common import MAX_NUMBER_SQS_MESSAGES_TO_RECEIVE
from ..mws.mws import MWSError

MAX_NUMBER_FEED_TO_PROCESS = 5000000

_logger = logging.getLogger(__name__)

try:
    from ..mws.mws import Products
    from ..mws.mws import Orders
    from ..mws.mws import Reports
    from ..mws.mws import Feeds

except ImportError:
    pass
_logger.debug("Cannot import 'amazon' API")

AMAZON_DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%S'

AMAZON_ORDER_ID_PATTERN = '^([\d]{3}-[\d]{7}-[\d]{7})+$'

AMAZON_SUBMIT_REPORT_METHOD_DICT = {'submit_inventory_request':'_GET_MERCHANT_LISTINGS_ALL_DATA_',
                                    'submit_sales_request':'_GET_FLAT_FILE_ORDERS_DATA_',
                                    'submit_updated_sales_request':'_GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE_',
                                    'submit_feedbacks_report_request':'_GET_SELLER_FEEDBACK_DATA_',
                                    'submit_metrics_account_request':'_GET_V1_SELLER_PERFORMANCE_REPORT_',
                                    'submit_fee_product_request':'_GET_REFERRAL_FEE_PREVIEW_REPORT_'}

AMAZON_METHOD_LIST = ['get_inventory',
                      'get_sales',
                      'get_order',
                      'get_customer_feedbacks',
                      'get_products_for_id',
                      'list_items_from_order',
                      'get_category_product',
                      'get_my_price_product',
                      'get_lowest_price_and_buybox',
                      'get_offers_changed',
                      'save_feed_response',
                      'amazon_sale_order_read',
                      'amazon_sale_order_search',
                      'amazon_product_product_read',
                      'submit_stock_update',
                      'submit_price_update',
                      'submit_add_inventory_request',
                      'submit_stock_price_update',
                      'submit_confirm_shipment',
                      'submit_feeds',
                      ]


# noinspection Pylint
class AmazonAPI(object):

    def __init__(self, backend):
        self._backend = backend
        self._sqs = None

    def __enter__(self, *args, **kwargs):
        return self

    def __exit__(self, *args, **kwargs):
        return self

    @api.model
    def _get_odoo_datetime_format(self, iso_date):
        if iso_date:
            try:
                str_date = Datetime.to_string(dateutil.parser.parse(iso_date))
                return str_date
            except:
                return ''
        return ''

    @api.model
    def _get_odoo_date_format(self, iso_date):
        if iso_date:
            try:
                str_date = Date.to_string(dateutil.parser.parse(iso_date))
                return str_date
            except:
                return ''
        return ''

    def batch_update_feeds(self, feeds):
        if feeds:
            with api.Environment.manage():
                with odoo.registry(
                        feeds.env.cr.dbname).cursor() as new_cr:
                    new_env = api.Environment(new_cr, feeds.env.uid,
                                              feeds.env.context)
                    try:
                        while feeds:
                            batch_update = feeds[0:1000]
                            feeds -= batch_update
                            # do not attach new env to self because it may be
                            # huge, and the cache is cleaned after each unlink
                            # so we do not want to much record is the env in
                            # which we call unlink because odoo would prefetch
                            # fields, cleared right after.
                            batch_update.with_env(new_env).write({'launched':True, 'date_launched':datetime.now().isoformat(sep=' ')})
                            new_env.cr.commit()
                    except Exception as e:
                        _logger.exception(
                            "Failed to update feeds : %s" % (feeds._name, str(e)))

    @api.model
    def _get_offers_changed(self):
        if not self._backend.sqs_account_id:
            _logger.info('There aren\'t sqs accounts configured for this backend (%s)' % self._backend.name)
        else:
            return self._get_messages_of_sqs_account()
        return

    def _submit_feeds(self):
        """
        Method that get feeds of our database and submit the method of every type of feed
        :return: None
        """
        feeds_to_throw = self._backend.env['amazon.feed.tothrow'].search([('backend_id', '=', self._backend.id),
                                                                          ('launched', '=', False), ],
                                                                         order='type',
                                                                         limit=MAX_NUMBER_FEED_TO_PROCESS)

        if feeds_to_throw:

            try:
                # If there are migrate feeds this method is the charge of add inventory feeds
                migrate_backend_feeds = feeds_to_throw.filtered(lambda f:f.type == 'Migrate_backend')
                if migrate_backend_feeds:
                    self._migrate_backend_feeds(migrate_feeds=migrate_backend_feeds)
            except Exception as e:
                _logger.error('Error has been ocurred on feeds migrate backend(%s): %s' % (self._backend.name, e.message))

            try:
                add_inventory_feeds = feeds_to_throw.filtered(lambda f:f.type == '_POST_FLAT_FILE_INVLOADER_DATA_')
                if add_inventory_feeds:
                    self._submit_add_inventory_request(arguments=add_inventory_feeds)
            except Exception as e:
                _logger.error('Error has been ocurred on feeds add inventory(%s): %s' % (self._backend.name, e.message))

            try:
                confirm_shipments = feeds_to_throw.filtered(lambda f:f.type == '_POST_FLAT_FILE_FULFILLMENT_DATA_')
                if confirm_shipments:
                    self._submit_confirm_shipment(arguments=confirm_shipments)
            except Exception as e:
                _logger.error('Error has been ocurred on feeds confirm shipments(%s): %s' % (self._backend.name, e.message))

            try:
                update_stock_feeds = feeds_to_throw.filtered(lambda f:f.type == '_POST_INVENTORY_AVAILABILITY_DATA_')

                if update_stock_feeds:
                    self._submit_stock_update(arguments=update_stock_feeds)
            except Exception as e:
                _logger.error('Error has been ocurred on feeds stock update(%s): %s' % (self._backend.name, e.message))

            try:
                update_stock_price_feeds = feeds_to_throw.filtered(lambda f:f.type == '_POST_FLAT_FILE_PRICEANDQUANTITYONLY_UPDATE_DATA_')
                if update_stock_price_feeds:
                    self._submit_stock_price_update(arguments=update_stock_price_feeds)
            except Exception as e:
                _logger.error('Error has been ocurred on feeds update stock price(%s): %s' % (self._backend.name, e.message))

            try:
                delete_inventory_feeds = feeds_to_throw.filtered(lambda f:f.type == '_POST_PRODUCT_DATA_DELETE_')
                if delete_inventory_feeds:
                    self._submit_delete_inventory_request(arguments=delete_inventory_feeds)
            except Exception as e:
                _logger.error('Error has been ocurred on feeds add inventory(%s): %s' % (self._backend.name, e.message))

    def _save_feed(self, response, params, xml_csv):
        """
        Method to save the feed that have been launched rigth now
        :param response:
        :param params:
        :param xml_csv:
        :return:
        """
        amz_feed = self._backend.env['amazon.feed']
        if response and response._response_dict and response._response_dict[response._rootkey] and response._response_dict[response._rootkey].get(
                'FeedSubmissionInfo'):
            info_feed = response._response_dict[response._rootkey].get('FeedSubmissionInfo')
            type_feed = [x[0] for x in amz_feed.get_feed_types() if x[0] == info_feed.getvalue('FeedType')]
            vals = {'id_feed_submision':info_feed.getvalue('FeedSubmissionId'),
                    'type':type_feed[0] if type_feed else '',
                    'submitted_date':info_feed.getvalue('SubmittedDate'),
                    'feed_processing_status':info_feed.getvalue('FeedProcessingStatus'),
                    'params':params.encode('utf8') if params else None,
                    'xml_csv':xml_csv.decode('utf8') if xml_csv else None,
                    'backend_id':self._backend.id}

            amz_feed.create(vals)

            feed_model = self._backend.env['amazon.feed']
            delayable = feed_model.with_delay(priority=8, eta=datetime.now() + timedelta(minutes=15))
            vals = {'method':'get_feed_result',
                    'feed_id':info_feed.getvalue('FeedSubmissionId')}
            delayable.description = '%s.%s' % (feed_model._name, 'get_feed_result(%s)' % info_feed.getvalue('FeedSubmissionId'))
            delayable.import_record(self._backend, vals)

            return info_feed.getvalue('FeedSubmissionId')
        return

    def _submit_delete_inventory_request(self, arguments):
        """
        Method to delete product from Amazon inventory
        :param arguments: feeds with the data to get
        :return: ids of the feeds submitted
        """
        feedsApi = Feeds(backend=self._backend)

        top = etree.Element('AmazonEnvelope')

        header = etree.SubElement(top, 'Header')
        docVersion = etree.SubElement(header, 'DocumentVersion')
        docVersion.text = '1.01'
        merchantId = etree.SubElement(header, 'MerchantIdentifier')
        merchantId.text = self._backend.token

        messageType = etree.SubElement(top, 'MessageType')
        messageType.text = 'Product'

        dict_products = {}

        '''
        Dict structure
        dict_products = {'A1RKKUPIHCS9HS':
                        {'D5-0BJZ-39B4': {'sku': 'D5-0BJZ-39B4'},
                         'CH-N74Z-DD0S': {'sku': 'CH-N74Z-DD0S'},
                         '9P-NBB6-095H': {'sku': '9P-NBB6-095H'}}}

                         {'amazon_product_id': 70144, 'new_backend_id': 6, 'marketplace_ids': [1, 2, 3, 4, 5, 9]}
        '''
        for feed_to_throw in arguments:
            element = ast.literal_eval(feed_to_throw.data)
            element['create_date'] = feed_to_throw.create_date
            amazon_product = self._backend.env['amazon.product.product'].browse(element['amazon_product_id'])
            marketplaces = self._backend.env['amazon.config.marketplace'].browse(element['marketplace_ids'])

            for market in marketplaces:

                # If there isn't the markeplace added we add this
                if not dict_products.get(market.id_mws):
                    dict_products[market.id_mws] = {}

                # We check if the sku is added on this marketplace
                if not dict_products[market.id_mws].get(amazon_product.sku):
                    dict_products[market.id_mws][amazon_product.sku] = {'sku':amazon_product.sku, 'create_date':element['create_date']}
                elif dict_products[market.id_mws][amazon_product.sku]['create_date'] < element['create_date']:
                    dict_products[market.id_mws].pop(amazon_product.sku)
                    dict_products[market.id_mws][amazon_product.sku] = {'sku':amazon_product.sku, 'create_date':element['create_date']}

        ids = []
        for id_market in dict_products.keys():
            i = 1

            for product in dict_products[id_market].values():
                message = etree.SubElement(top, 'Message')
                messageID = etree.SubElement(message, 'MessageID')
                messageID.text = str(i)
                i += 1

                operationType = etree.SubElement(message, 'OperationType')
                operationType.text = 'Delete'

                product_node = etree.SubElement(message, 'Product')

                sku = etree.SubElement(product_node, 'SKU')
                sku.text = product['sku']

            xml = etree.tostring(top, pretty_print=True, xml_declaration=True, encoding='UTF-8')

            xml = xml.replace('<AmazonEnvelope>',
                              '<AmazonEnvelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="amzn-envelope.xsd">')

            _logger.info('_POST_PRODUCT_DATA_ - Delete product feed: [%s]' % xml)
            response = feedsApi.submit_feed(feed=xml,
                                            feed_type='_POST_PRODUCT_DATA_',
                                            marketplaceids=[id_market])

            ids.append({'id_feed':self._save_feed(response=response, params=str(arguments), xml_csv=xml) or 'Error',
                        'id_mws':id_market})

        return ids

    def _migrate_backend_feeds(self, migrate_feeds):
        """

        :param migrate_feeds:
        :param add_inventory_feeds:
        :return:
        """
        self._submit_delete_inventory_request(migrate_feeds)
        for feed in migrate_feeds:
            element = ast.literal_eval(feed.data)
            amazon_product = self._backend.env['amazon.product.product'].browse(element['amazon_product_id'])
            for market_id in element['marketplace_ids']:
                detail = amazon_product.get_market_detail_product(market_id)
                market = self._backend.env['amazon.config.marketplace'].browse(market_id)
                row = {}
                row['sku'] = amazon_product.sku
                row['product-id'] = amazon_product.asin
                row['product-id-type'] = 'ASIN'
                price = detail.price
                row['price'] = ("%.2f" % price).replace('.', market.decimal_currency_separator) if price else ''
                row['minimum-seller-allowed-price'] = ''
                row['maximum-seller-allowed-price'] = ''
                row['item-condition'] = '11'  # We assume the products are new
                row['quantity'] = str(int(amazon_product.amazon_qty or 0))
                row['add-delete'] = 'a'
                row['will-ship-internationally'] = ''
                row['expedited-shipping'] = ''
                row['merchant-shipping-group-name'] = ''
                handling_time = amazon_product.odoo_id._compute_amazon_handling_time() or ''
                row['handling-time'] = str(int(handling_time or 0)) if price else amazon_product.handling_time
                row['item_weight'] = ''
                row['item_weight_unit_of_measure'] = ''
                row['item_volume'] = ''
                row['item_volume_unit_of_measure'] = ''
                row['id_mws'] = market.id_mws

                vals = {'backend_id':element['new_backend_id'],
                        'type':'_POST_FLAT_FILE_INVLOADER_DATA_',
                        'model':amazon_product._name,
                        'identificator':amazon_product.id,
                        'data':row,
                        }

                self._backend.env['amazon.feed.tothrow'].create(vals)

            amazon_product.backend_id = element['new_backend_id']

        self.batch_update_feeds(migrate_feeds)

    def _submit_stock_update(self, arguments):
        """
        Method to update the stock on Amazon
        :param arguments: feeds with the data to get
        :return: ids of the feeds submitted
        """
        feedsApi = Feeds(backend=self._backend)

        dict_products = {}

        '''
        Dict structure
        dict_products = {'A1RKKUPIHCS9HS':
                        {'D5-0BJZ-39B4': {'sku': 'D5-0BJZ-39B4', 'Quantity': 2, 'id_mws':'A1RKKUPIHCS9HS'},
                         'CH-N74Z-DD0S': {'sku': 'CH-N74Z-DD0S', 'Quantity': 5,'id_mws':'A1RKKUPIHCS9HS'},
                         '9P-NBB6-095H': {'sku': '9P-NBB6-095H', 'Quantity': 4, 'id_mws': 'A1RKKUPIHCS9HS'}}}
        '''
        for feed_to_throw in arguments:
            element = ast.literal_eval(feed_to_throw.data)
            element['create_date'] = feed_to_throw.create_date
            # If there isn't the markeplace added we add this
            if not dict_products.get(element['id_mws']):
                dict_products[element['id_mws']] = {}

            # We check if the sku is added on this marketplace
            if not dict_products[element['id_mws']].get(element['sku']):
                dict_products[element['id_mws']][element['sku']] = element
            elif dict_products[element['id_mws']][element['sku']]['create_date'] < element['create_date']:
                dict_products[element['id_mws']].pop(element['sku'])
                dict_products[element['id_mws']][element['sku']] = element

        ids = []
        for id_market in dict_products.keys():
            i = 1

            top = etree.Element('AmazonEnvelope')

            header = etree.SubElement(top, 'Header')
            docVersion = etree.SubElement(header, 'DocumentVersion')
            docVersion.text = '1.01'
            merchantId = etree.SubElement(header, 'MerchantIdentifier')
            merchantId.text = self._backend.token

            messageType = etree.SubElement(top, 'MessageType')
            messageType.text = 'Inventory'

            for product in dict_products[id_market].values():
                message = etree.SubElement(top, 'Message')
                messageID = etree.SubElement(message, 'MessageID')
                messageID.text = str(i)
                i += 1

                operationType = etree.SubElement(message, 'OperationType')
                operationType.text = 'Update'

                inventory = etree.SubElement(message, 'Inventory')

                sku = etree.SubElement(inventory, 'SKU')
                sku.text = product['sku']
                quantity = etree.SubElement(inventory, 'Quantity')
                quantity.text = str(product['Quantity'])

            xml = etree.tostring(top, pretty_print=True, xml_declaration=True, encoding='UTF-8')

            xml = xml.replace('<AmazonEnvelope>',
                              '<AmazonEnvelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="amzn-envelope.xsd">')

            _logger.info('_POST_INVENTORY_AVAILABILITY_DATA_ feed: [%s]' % xml)
            response = feedsApi.submit_feed(feed=xml,
                                            feed_type='_POST_INVENTORY_AVAILABILITY_DATA_',
                                            marketplaceids=[id_market])

            ids.append({'id_feed':self._save_feed(response=response, params=str(arguments), xml_csv=xml) or 'Error', 'id_mws':id_market})

            xml = None

        self.batch_update_feeds(arguments)

        return ids

    def _submit_price_update(self, arguments):
        # TODO we need to decide if this method is necesary. Right now it doesn't work
        """

        :param arguments:
        :return:
        """
        feedsApi = Feeds(backend=self._backend)

        dict_products = arguments

        '''
        Dict structure
        dict_products = {
                         'A1RKKUPIHCS9HS': {
                            'D5-0BJZ-39B4':
                                    {'sku': 'D5-0BJZ-39B4', 'price': '84.80', currency:'EUR', 'id_mws':'A1RKKUPIHCS9HS'},
                            'CH-N74Z-DD0S':
                                    {'sku': 'CH-N74Z-DD0S', 'price': '24,45', currency:'EUR', 'id_mws':'A1RKKUPIHCS9HS'}
                            }
                        }
        '''
        feed_ids = []
        for id_market in dict_products.keys():
            i = 1

            top = etree.Element('AmazonEnvelope')

            header = etree.SubElement(top, 'Header')
            docVersion = etree.SubElement(header, 'DocumentVersion')
            docVersion.text = '1.01'
            merchantId = etree.SubElement(header, 'MerchantIdentifier')
            merchantId.text = self._backend.token

            messageType = etree.SubElement(top, 'MessageType')
            messageType.text = 'Price'

            for product in dict_products[id_market].values():
                message = etree.SubElement(top, 'Message')
                messageID = etree.SubElement(message, 'MessageID')
                messageID.text = str(i)

                operationType = etree.SubElement(message, 'OperationType')
                operationType.text = 'Update'

                price = etree.SubElement(message, 'Price')

                sku = etree.SubElement(price, 'SKU')
                sku.text = product['sku']
                standard_price = etree.SubElement(price, 'StandardPrice')
                standard_price.text = product['price']
                standard_price.set('currency', product['currency'])
                i += 1

            xml = etree.tostring(top, pretty_print=True, xml_declaration=True, encoding='UTF-8')

            xml = xml.replace('<AmazonEnvelope>',
                              '<AmazonEnvelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="amzn-envelope.xsd">')

            _logger.info('_POST_PRODUCT_PRICING_DATA_ feed: [%s]' % xml)

            response = feedsApi.submit_feed(feed=xml,
                                            feed_type='_POST_PRODUCT_PRICING_DATA_',
                                            marketplaceids=[id_market])

            feed_ids.append(self._save_feed(response=response, params=str(arguments), xml_csv=xml))

            xml = None

        return feed_ids

    def _submit_stock_price_update(self, arguments):
        """
        Send the csv file as it is described on https://s3.amazonaws.com/seller-templates/ff/eu/es/Flat.File.PriceInventory.es.xls
        :param arguments:
        :return:
        """
        feedsApi = Feeds(backend=self._backend)

        dict_products = {}

        '''
        Dict structure
        dict_products = [{'sku': 'D5-0BJZ-39B4', 'price': '84.80', 'Quantity': 4, 'id_mws':'A1RKKUPIHCS9HS', 'handling_time':2},
                         {'sku': 'CH-N74Z-DD0S', 'price': '24,45', 'Quantity': 5, 'id_mws':'A1RKKUPIHCS9HS', 'handling_time':4}]
        '''

        for feed_to_throw in arguments:
            element = ast.literal_eval(feed_to_throw.data)
            element['create_date'] = feed_to_throw.create_date
            # If there isn't the markeplace added we add this
            if not dict_products.get(element['id_mws']):
                dict_products[element['id_mws']] = {}

            # We check if the sku is added on this marketplace
            if not dict_products[element['id_mws']].get(element['sku']):
                dict_products[element['id_mws']][element['sku']] = element
            elif dict_products[element['id_mws']][element['sku']]['create_date'] < element['create_date']:
                dict_products[element['id_mws']].pop(element['sku'])
                dict_products[element['id_mws']][element['sku']] = element

        feed_ids = []
        for id_market in dict_products.keys():

            titles = ('sku', 'price', 'minimum-seller-allowed-price', 'maximum-seller-allowed-price', 'quantity', 'fulfillment-channel', 'leadtime-to-ship')
            csv_data = '\t'
            csv_data = csv_data.join(titles) + '\n'

            for product in dict_products[id_market].values():
                data = '\t'
                product_data = (product.get('sku') or '', product.get('Price') or '', product.get('minimum-seller-allowed-price') or '',
                                product.get('maximum-seller-allowed-price') or '', product.get('Quantity') or '0',
                                product.get('fulfillment-channel') or '',
                                product.get('handling-time') or '')
                data = data.join(product_data) + '\n'
                csv_data = csv_data + data

            _logger.info('_POST_FLAT_FILE_PRICEANDQUANTITYONLY_UPDATE_DATA_ feed: [%s]' % csv_data)

            response = feedsApi.submit_feed(feed=csv_data,
                                            feed_type='_POST_FLAT_FILE_PRICEANDQUANTITYONLY_UPDATE_DATA_',
                                            marketplaceids=[id_market])

            feed_ids.append(self._save_feed(response=response, params=str(arguments), xml_csv=csv_data))

        # We are going to write the feed as launched
        self.batch_update_feeds(arguments)

        return feed_ids

    def _submit_add_inventory_request(self, arguments):
        """
        Send a csv feed as it is described in https://s3.amazonaws.com/seller-templates/ff/eu/es/Flat.File.InventoryLoader.es.xls
        :param arguments:
        :return:
        """

        feedsApi = Feeds(backend=self._backend)

        '''
        Dict structure
        dict_products = [{'sku': 'D5-0BJZ-39B4', 'product-id-type': 'ASIN', 'product-id': 'B31N70DRX0', 'item-condition': '11', 'price': '84,80', 'Quantity': 4, 'id_mws':'A1RKKUPIHCS9HS', 'handling_time':2},
                         {'sku': 'CH-N74Z-DD0S', 'product-id-type': 'ASIN', 'product-id': 'B44S70ERQA', 'item-condition': '11', 'price': '24,45', 'Quantity': 5, 'id_mws':'A1RKKUPIHCS9HS', 'handling_time':4}]
        '''

        dict_products = {}

        # We are going to create a dict to transform on csv
        for feed_to_throw in arguments:
            element = ast.literal_eval(feed_to_throw.data)
            element['create_date'] = feed_to_throw.create_date

            if not dict_products.get(element['id_mws']):
                dict_products[element['id_mws']] = {}

            # We check if the sku is added on this marketplace
            if not dict_products[element['id_mws']].get(element['sku']):
                dict_products[element['id_mws']][element['sku']] = element
            elif dict_products[element['id_mws']][element['sku']]['create_date'] < element['create_date']:
                dict_products[element['id_mws']].pop(element['sku'])
                dict_products[element['id_mws']][element['sku']] = element

        feed_ids = []

        for id_market in dict_products.keys():

            titles = ('sku', 'product-id', 'product-id-type', 'price', 'minimum-seller-allowed-price', 'maximum-seller-allowed-price', 'item-condition',
                      'quantity', 'add-delete', 'will-ship-internationally', 'expedited-shipping', 'item-note', 'merchant-shipping-group-name',
                      'product_tax_code', 'fulfillment_center_id', 'handling-time', 'batteries_required', 'are_batteries_included',
                      'battery_cell_composition', 'battery_type', 'number_of_batteries', 'battery_weight', 'battery_weight_unit_of_measure',
                      'number_of_lithium_ion_cells', 'number_of_lithium_metal_cells', 'lithium_battery_packaging', 'lithium_battery_energy_content',
                      'lithium_battery_energy_content_unit_of_measure', 'lithium_battery_weight', 'lithium_battery_weight_unit_of_measure',
                      'supplier_declared_dg_hz_regulation1', 'supplier_declared_dg_hz_regulation2', 'supplier_declared_dg_hz_regulation3',
                      'supplier_declared_dg_hz_regulation4', 'supplier_declared_dg_hz_regulation5', 'hazmat_united_nations_regulatory_id', 'handling-time',
                      'safety_data_sheet_url', 'item_weight', 'item_weight_unit_of_measure', 'item_volume', 'item_volume_unit_of_measure', 'flash_point',
                      'ghs_classification_class1', 'ghs_classification_class2', 'ghs_classification_class3', 'list_price', 'uvp_list_price')
            csv_data = '\t'
            csv_data = csv_data.join(titles) + '\n'

            for product in dict_products[id_market].values():
                data = '\t'
                product_data = (product.get('sku') or '', product.get('product-id') or '', product.get('product-id-type') or '', product.get('price') or '',
                                product.get('minimum-seller-allowed-price') or '', product.get('maximum-seller-allowed-price') or '',
                                product.get('item-condition') or '',
                                str(product.get('quantity') or 0) or '', product.get('add-delete') or '', product.get('will-ship-internationally') or '',
                                product.get('expedited-shipping') or '', product.get('item-note') or '', product.get('merchant-shipping-group-name') or '',
                                product.get('product_tax_code') or '', product.get('fulfillment_center_id') or '', str(product.get('handling-time') or 0) or '',
                                product.get('batteries_required') or '', product.get('are_batteries_included') or '',
                                product.get('battery_cell_composition') or '',
                                product.get('battery_type') or '', product.get('number_of_batteries') or '', product.get('battery_weight') or '',
                                product.get('battery_weight_unit_of_measure') or '', product.get('number_of_lithium_ion_cells') or '',
                                product.get('number_of_lithium_metal_cells') or '', product.get('lithium_battery_packaging') or '',
                                product.get('lithium_battery_energy_content') or '', product.get('lithium_battery_energy_content_unit_of_measure') or '',
                                product.get('lithium_battery_weight') or '', product.get('lithium_battery_weight_unit_of_measure') or '',
                                product.get('supplier_declared_dg_hz_regulation1') or '', product.get('supplier_declared_dg_hz_regulation2') or '',
                                product.get('supplier_declared_dg_hz_regulation3') or '', product.get('supplier_declared_dg_hz_regulation4') or '',
                                product.get('supplier_declared_dg_hz_regulation5') or '', product.get('hazmat_united_nations_regulatory_id') or '',
                                ''  # second field handling-time, this need to be empty
                                , product.get('safety_data_sheet_url') or '', product.get('item_weight') or '',
                                product.get('item_weight_unit_of_measure') or '', product.get('item_volume') or '',
                                product.get('item_volume_unit_of_measure') or '',
                                product.get('flash_point') or '', product.get('ghs_classification_class1') or '',
                                product.get('ghs_classification_class2') or '',
                                product.get('ghs_classification_class3') or '', product.get('list_price') or '', product.get('uvp_list_price') or '', '\n')
                data = data.join(product_data) + '\n'
                csv_data = csv_data + data

            _logger.info('_POST_FLAT_FILE_INVLOADER_DATA_ feed: [%s]' % csv_data)

            response = feedsApi.submit_feed(feed=csv_data,
                                            feed_type='_POST_FLAT_FILE_INVLOADER_DATA_',
                                            marketplaceids=[id_market])

            feed_ids.append(self._save_feed(response=response, params=str(arguments), xml_csv=csv_data))

        self.batch_update_feeds(arguments)

        with odoo.registry(arguments.env.cr.dbname).cursor() as new_cr:
            new_env = api.Environment(new_cr, arguments.env.uid, arguments.env.context)

        return feed_ids

    def _submit_confirm_shipment(self, arguments):
        """
        Send the csv file as it is described on https://s3.amazonaws.com/seller-templates/ff/eu/es/Flat.File.PriceInventory.es.xls
        :param arguments: csv
        :return:
        """
        feedsApi = Feeds(backend=self._backend)

        feed_ids = []

        """
        f = StringIO(arguments)
        reader = csv.reader(f, delimiter='\t', lineterminator='\n')
        first_row=True
        csv_data = '\t'
        for row in reader:
            if first_row:
                csv_data = '\t'
                csv_data = csv_data.join(row) + '\n'
                first_row=False
                continue
            data = '\t'
            row.append('\n')
            csv_data = csv_data + data.join(row)
        """
        for feed_to_throw in arguments:
            element = ast.literal_eval(feed_to_throw.data)

            _logger.info('_POST_FLAT_FILE_FULFILLMENT_DATA_ feed: [%s]' % arguments)

            response = feedsApi.submit_feed(feed=element['csv'],
                                            feed_type='_POST_FLAT_FILE_FULFILLMENT_DATA_',
                                            marketplaceids=[self._backend._get_marketplace_default().id_mws])

            feed_ids.append(self._save_feed(response=response, params=str(arguments), xml_csv=arguments))

        self.batch_update_feeds(arguments)

        return feed_ids

    def _submit_report(self, method, arguments=None):
        try:
            report_api = Reports(backend=self._backend)

            marketplaces = self._backend._get_crypt_codes_marketplaces()
            report_ids = []

            date_start = None
            date_end = None
            if arguments:
                if arguments.get('date_start'):
                    date_start = arguments['date_start']
                if arguments.get('date_end'):
                    date_end = arguments['date_end']

            for market in marketplaces:

                response = report_api.request_report(report_type=AMAZON_SUBMIT_REPORT_METHOD_DICT[method],
                                                     marketplaceids=[market],
                                                     start_date=date_start,
                                                     end_date=date_end)

                if response and response._response_dict and response._response_dict[response._rootkey] and \
                        response._response_dict[response._rootkey].get('ReportRequestInfo') and \
                        response._response_dict[response._rootkey]['ReportRequestInfo'].get('ReportRequestId'):
                    report_ids.append((response._response_dict[response._rootkey]['ReportRequestInfo']['ReportRequestId']['value'], market))

            return {'report_ids':report_ids}


        except Exception as e:
            _logger.error("report_api(%s.%s) failed", '_submit_report', method)
            return e

    def _get_report_list_ids(self, report_ids):
        try:
            report_api = Reports(backend=self._backend)

            response = report_api.get_report_list(requestids=[report_ids])

            if response and response._response_dict and response._response_dict[response._rootkey] and \
                    response._response_dict[response._rootkey].get('ReportInfo') and \
                    response._response_dict[response._rootkey]['ReportInfo'].get('ReportId'):
                return response._response_dict[response._rootkey]['ReportInfo']['ReportId']['value']
        except Exception as e:
            _logger.error("report_api(%s) failed with report_ids %s", '_get_report_list_ids ', report_ids)
            raise e

        return

    def _get_report(self, report_list_id):
        report_api = Reports(backend=self._backend)

        try:
            response = report_api.get_report(report_id=report_list_id)
            if response and response.response and response.response.status_code == 200:
                return response
        except MWSError as e:
            _logger.error("report_api(%s) failed with report_ids %s", '_get_report ', report_list_id)
            if len(e.args) and e.args[0].lower().index('request is throttled'):
                raise RetryableJobError(msg='The request to get_report is throttled, we must wait 5 minutes', seconds=300, ignore_retry=True)
            raise FailedJobError('The request to get report failed: report_list_id: %s (%s)', report_list_id, e.args[0] if len(e.args) and e.args[0] else '')
        except Exception as e:
            raise e

    def _get_parent_category(self, dict_category):
        if dict_category.get('Parent'):
            return self._get_parent_category(dict_category.get('Parent'))
        return dict_category.getvalue('ProductCategoryName')

    def _get_lowest_price_and_buybox(self, sku, marketplace_id, product_api=None):

        if not product_api:
            product_api = Products(backend=self._backend)

        try:
            list_offer = []
            response = product_api.get_lowest_priced_offers_for_sku(marketplaceid=marketplace_id, sku=sku)
            if response and response._response_dict and response._response_dict[response._rootkey] and \
                    response._response_dict[response._rootkey].get('Offers') and response._response_dict[response._rootkey]['Offers']['Offer']:

                offers = response._response_dict[response._rootkey]['Offers']['Offer']
                if not isinstance(offers, list):
                    offers = [offers]

                for aux in offers:
                    offer = {}
                    offer['has_buy_box'] = aux.getvalue('IsBuyBoxWinner')
                    offer['amazon_fulfilled'] = aux.getvalue('IsFulfilledByAmazon')
                    offer['my_offer'] = aux.getvalue('MyOffer')
                    if offer['my_offer'] and offer['my_offer'] == 'true':
                        offer['id_seller'] = self._backend.seller
                        offer['is_our_offer'] = True
                    offer['feedback_rating'] = aux['SellerFeedbackRating'].getvalue('SellerPositiveFeedbackRating') if aux.get('SellerFeedbackRating') else ''
                    offer['ship_price'] = aux['Shipping'].getvalue('Amount')
                    offer['ship_currency'] = aux['Shipping'].getvalue('CurrencyCode')
                    offer['price'] = aux['ListingPrice'].getvalue('Amount')
                    offer['currency_price'] = aux['ListingPrice'].getvalue('CurrencyCode')
                    offer['max_hours_ship'] = aux['ShippingTime'].getvalue('maximumHours')
                    offer['min_hours_ship'] = aux['ShippingTime'].getvalue('minimumHours')
                    offer['country_ship_from'] = aux['ShipsFrom'].getvalue('Country') if aux.get('ShipsFrom') else ''
                    offer['country_ship_id'] = self._backend.env['res.country'].search([('code', '=', offer['country_ship_from'])]).id if offer[
                        'country_ship_from'] else ''
                    offer['condition'] = aux.getvalue('SubCondition')
                    offer['buybox_winner'] = aux.getvalue('IsBuyBoxWinner')
                    list_offer.append(offer)

            return list_offer


        except Exception as e:
            _logger.error("Recovering lowest prices from product_api (%s) failed with sku %s and marketplace %s",
                          '_get_product_data ', sku, marketplace_id)
            raise e

        return

    def _get_main_data_product(self, sku, marketplace_id, product_api=None, product={}):
        if not product_api:
            product_api = Products(backend=self._backend)

        try:
            response = product_api.get_matching_product_for_id(type_='SellerSKU', ids=[sku], marketplaceid=marketplace_id)

            if response and response._response_dict and response._response_dict[response._rootkey] and \
                    response._response_dict[response._rootkey].get('Products'):
                products = response._response_dict[response._rootkey]['Products']
                aux = products['Product']['AttributeSets']['ItemAttributes']
                if isinstance(aux, list):
                    _logger.error('There are several products on a get_product_data search')
                    exc = Exception()
                    raise exc
                product['marketplace_id_crypt'] = marketplace_id
                product['title'] = aux.getvalue('Title')
                product['brand'] = aux.getvalue('Brand')
                product['url_images'] = []
                # Remove the _SL75_ extension to get the real size image
                product['url_images'].append(None if not aux.get('SmallImage') else re.sub('._SL75_', '', aux['SmallImage'].getvalue('URL')))
                product['productgroup'] = aux.getvalue('ProductGroup')
                if aux.get('PackageDimensions'):
                    dimensions = aux.get('PackageDimensions')
                    product['height'] = dimensions.get('Height')
                    product['length'] = dimensions.get('Length')
                    product['width'] = dimensions.get('Width')
                    product['weight'] = dimensions.get('Weight')
        except Exception as e:
            _logger.error("Recovering main data from product_api (%s) failed with sku %s and marketplace %s", 'get_main_data_product', sku,
                          marketplace_id)
            raise e

        return product

    def _get_product_from_response_read(self, prod_dict):
        product = {}
        identifiers = prod_dict['Identifiers']['MarketplaceASIN']
        product['asin'] = identifiers.getvalue('ASIN')
        attributes = prod_dict['AttributeSets']['ItemAttributes']
        product['marketplace_id_crypt'] = identifiers.getvalue('MarketplaceId')
        product['title'] = attributes.getvalue('Title')
        product['brand'] = attributes.getvalue('Brand')
        product['url_images'] = []
        # Remove the _SL75_ extension to get the real size image
        product['url_images'].append(None if not attributes.get('SmallImage') else re.sub('._SL75_', '', attributes['SmallImage'].getvalue('URL')))
        product['productgroup'] = attributes.getvalue('ProductGroup')
        if attributes.get('PackageDimensions'):
            dimensions = attributes.get('PackageDimensions')
            product['height'] = dimensions.get('Height')
            product['length'] = dimensions.get('Length')
            product['width'] = dimensions.get('Width')
            product['weight'] = dimensions.get('Weight')
        return product

    def _get_products_for_id(self, ids, marketplace_id, type_id, product_api=None):
        if not product_api:
            product_api = Products(backend=self._backend)

        # If we haven't type id (ASIN, EAN,UPC...) we are going to try to get it
        if not type_id:
            type_id = self._check_type_identifier(ids[0])

        if type_id:
            try:
                response = product_api.get_matching_product_for_id(type=type_id, ids=ids, marketplaceid=marketplace_id)

                if response and response._response_dict and response._response_dict[response._rootkey] and \
                        response._response_dict[response._rootkey] and response._response_dict[response._rootkey].get('Products'):
                    if not isinstance(response._response_dict[response._rootkey], list):
                        ids_searched = [response._response_dict[response._rootkey]]
                    list_products = []
                    for prod_dict in ids_searched:
                        products = prod_dict['Products'].get('Product')
                        if not isinstance(products, list):
                            products = [products]
                        for subprod in products:
                            product = self._get_product_from_response_read(subprod)
                            product['id'] = prod_dict.getvalue('Id')
                            product['type_id'] = prod_dict.getvalue('IdType')

                            list_products.append(product)
                    return list_products
            except Exception as e:
                _logger.error("Recovering data from product_api (%s) failed with ids %s and marketplace %s", 'get_matching_product_for_id', ids, marketplace_id)
                raise e

        return []

    def _get_my_price_product(self, sku, marketplace_id, product_api=None, product={}, get_fee=True):
        if not product_api:
            product_api = Products(backend=self._backend)

        try:
            response = product_api.get_my_price_for_sku(marketplaceid=marketplace_id, skus=[sku])
            if response and response._response_dict and response._response_dict[response._rootkey] and \
                    response._response_dict[response._rootkey].get('Product') and response._response_dict[response._rootkey]['Product'].get('Offers') \
                    and response._response_dict[response._rootkey]['Product']['Offers'].get('Offer'):

                aux = response._response_dict[response._rootkey]['Product']['Offers']
                if isinstance(aux, list):
                    _logger.error('There are several offers on a get_product_data search')
                    exc = Exception()
                    raise exc
                offer = aux['Offer']
                # There are any situations on which MWS return more than one offer with different sku, we need filter this
                if isinstance(offer, list):
                    aux = aux['Offer']
                    for of in aux:
                        if of.getvalue('SellerSKU') == sku:
                            offer = of
                            break
                product['price_unit'] = offer['BuyingPrice']['ListingPrice'].getvalue('Amount')
                product['currency_price_unit'] = offer['BuyingPrice']['ListingPrice'].getvalue('CurrencyCode')
                product['price_shipping'] = offer['BuyingPrice']['Shipping'].getvalue('Amount')
                product['currency_shipping'] = offer['BuyingPrice']['Shipping'].getvalue('CurrencyCode')
                if get_fee:
                    try:
                        fee = self._get_my_estimate_fee(marketplace_id=marketplace_id,
                                                        type_sku_asin='SellerSKU',
                                                        id_type=sku,
                                                        price=product['price_unit'],
                                                        currency=product['currency_price_unit'],
                                                        ship_price=product['price_shipping'],
                                                        currency_ship=product['currency_shipping'])
                        if fee:
                            product['fee'] = fee
                    except Exception as efee:
                        _logger.error("Recovering fee product from product_api (%s) failed with sku %s and marketplace %s",
                                      'get_my_estimate_fee',
                                      sku,
                                      marketplace_id)

        except Exception as e:
            _logger.error("Recovering price's product from product_api (%s) failed with sku %s and marketplace %s", 'get_my_price_for_sku', sku, marketplace_id)
            raise e

        return product

    def _get_my_estimate_fee(self, marketplace_id, type_sku_asin, id_type, price, currency, ship_price=0, currency_ship=None, product_api=None):
        if not product_api:
            product_api = Products(backend=self._backend)

        if not currency_ship:
            currency_ship = currency

        response = product_api.get_my_fee_estimate(marketplaceids=[marketplace_id],
                                                   types=[type_sku_asin],
                                                   ids=[id_type],
                                                   prices=[price],
                                                   currency_prices=[currency],
                                                   shipping_prices=[ship_price],
                                                   currency_ship_prices=[currency_ship])

        if response and response._response_dict and response._response_dict[response._rootkey] and \
                response._response_dict[response._rootkey].get('FeesEstimateResultList') and \
                response._response_dict[response._rootkey]['FeesEstimateResultList'].get('FeesEstimateResult') and \
                response._response_dict[response._rootkey]['FeesEstimateResultList']['FeesEstimateResult'].get('FeesEstimate') and \
                response._response_dict[response._rootkey]['FeesEstimateResultList']['FeesEstimateResult']['FeesEstimate'].get('FeeDetailList') and \
                response._response_dict[response._rootkey]['FeesEstimateResultList']['FeesEstimateResult']['FeesEstimate']['FeeDetailList'].get('FeeDetail'):
            detail_list = response._response_dict[response._rootkey]['FeesEstimateResultList']['FeesEstimateResult']['FeesEstimate']['FeeDetailList'][
                'FeeDetail']

            fee = {}
            for detail in detail_list:
                fee['Amount'] = float(detail['FeeAmount'].getvalue('Amount')) if not fee.get('Amount') else \
                    fee['Amount'] + float(detail['FeeAmount'].getvalue('Amount'))
                fee['Promotion'] = float(detail['FeePromotion'].getvalue('Amount')) if not fee.get('Promotion') else \
                    fee['Promotion'] + float(detail['FeePromotion'].getvalue('Amount'))
                fee['Final'] = float(detail['FinalFee'].getvalue('Amount')) if not fee.get('Final') else \
                    fee['Final'] + float(detail['FinalFee'].getvalue('Amount'))

            return fee

    def _get_category_product(self, sku, marketplace_id, product_api=None, product={}):

        if not product_api:
            product_api = Products(backend=self._backend)

        try:
            response = product_api.get_product_categories_for_sku(marketplaceid=marketplace_id, sku=sku)
            if response and response._response_dict and response._response_dict[response._rootkey] and \
                    response._response_dict[response._rootkey].get('Self'):

                if isinstance(response._response_dict[response._rootkey]['Self'], list):
                    product['category_name'] = self._get_parent_category(response._response_dict[response._rootkey]['Self'][0])
                else:
                    product['category_name'] = self._get_parent_category(response._response_dict[response._rootkey]['Self'])
        except Exception as e:
            _logger.error("Recovering category from product_api (%s) failed with sku %s and marketplace %s", '_get_product_data ', sku, marketplace_id)
            raise e

        return product

    def _get_product_data(self, sku, marketplace_id):

        product_api = Products(backend=self._backend)

        product = {}

        product = self._get_main_data_product(sku, marketplace_id, product_api, product)

        product = self._get_my_price_product(sku, marketplace_id, product_api, product)

        return product

    def _get_order_data_from_dict(self, order_dict, with_items=True):
        order = {'order_id':order_dict.getvalue('AmazonOrderId')}
        order['date_order'] = self._get_odoo_datetime_format(order_dict.getvalue('PurchaseDate'))
        order['earlest_ship_date'] = self._get_odoo_datetime_format(order_dict.getvalue('EarliestShipDate'))
        order['lastest_ship_date'] = self._get_odoo_datetime_format(order_dict.getvalue('LatestShipDate'))
        order['earlest_delivery_date'] = self._get_odoo_datetime_format(order_dict.getvalue('EarliestDeliveryDate'))
        order['lastest_delivery_date'] = self._get_odoo_datetime_format(order_dict.getvalue('LatestDeliveryDate'))
        order['order_status_id'] = self._backend.env['amazon.config.order.status'].search([('name', '=', order_dict.getvalue('OrderStatus'))]).id
        order['is_prime'] = order_dict.getvalue('IsPrime')
        order['is_premium'] = order_dict.getvalue('IsPremiumOrder')
        order['is_business'] = order_dict.getvalue('IsBusinessOrder')
        order['ship_service_level'] = order_dict.getvalue('ShipmentServiceLevelCategory')
        order['FulfillmentChannel'] = order_dict.getvalue('FulfillmentChannel')
        order['number_items_shipped'] = order_dict.getvalue('NumberOfItemsShipped')
        order['number_items_unshipped'] = order_dict.getvalue('NumberOfItemsUnshipped')
        order['marketplace_id'] = order_dict.getvalue('MarketplaceId')
        if order_dict.get('OrderTotal'):
            order['total_amount'] = order_dict.get('OrderTotal').getvalue('Amount')
            order['currency'] = order_dict.get('OrderTotal').getvalue('CurrencyCode')

        # Get partner data
        order['partner'] = {'alias':order_dict.getvalue('BuyerName'),
                            'email':order_dict.getvalue('BuyerEmail'),
                            'phone':order_dict['ShippingAddress'].getvalue('Phone') if order_dict.get('ShippingAddress') else '', }
        # Get partner shipping address (only one address)
        if order_dict.get('ShippingAddress'):
            ship_address = order_dict['ShippingAddress']
            order['partner'].update({'name':ship_address.getvalue('Name'),
                                     'type':'delivery',
                                     'phone':ship_address.getvalue('Phone'),
                                     'street':ship_address.getvalue('AddressLine1'),
                                     'street2':ship_address.getvalue('AddressLine2'),
                                     'street3':ship_address.getvalue('AddressLine3'),
                                     'city':ship_address.getvalue('City'),
                                     'state':ship_address.getvalue('StateOrRegion'),
                                     'zip':ship_address.getvalue('PostalCode'),
                                     'country_id':ship_address.getvalue('CountryCode'),
                                     'marketplace_id':order_dict.getvalue('MarketplaceId'),
                                     })
        if with_items:
            try:
                self._list_items_from_order(order)
            except Exception as e:
                _logger.error("Getting list items order from order_api (%s) failed with id_order %s (%s)", '_get_order_data_from_dict',
                              order['order_id'],
                              e.message)

        return order

    def _list_items_from_order(self, order):
        '''
        Get the lines of the order
        :param order: order dictionary
        :return: Nothing, the lines are saved on a order param
        '''
        orders_api = Orders(backend=self._backend)
        response_item = orders_api.list_order_items(amazon_order_id=order['order_id'])
        if response_item and \
                response_item._response_dict and \
                response_item._response_dict[response_item._rootkey] and \
                response_item._response_dict[response_item._rootkey].get('OrderItems') and \
                response_item._response_dict[response_item._rootkey]['OrderItems'].get('OrderItem'):
            order['lines'] = []
            # If the result have one item, the result is a dict, however if the result have more than one item the result is a list
            items = response_item._response_dict[response_item._rootkey]['OrderItems']['OrderItem']
            items = items if isinstance(items, list) else [items]
            for order_item in items:
                item = {}
                item['sku'] = order_item.getvalue('SellerSKU')
                item['name'] = '[%s] %s' % (item['sku'], order_item.getvalue('Title'))
                item['marketplace_id'] = order['marketplace_id']
                item['asin'] = order_item.getvalue('ASIN')
                item['id_condition'] = order_item.getvalue('ConditionId')
                item['id_item'] = order_item.getvalue('OrderItemId')
                item['quantity_purchased'] = order_item.getvalue('QuantityOrdered')
                item['product_uom_qty'] = order_item.getvalue('QuantityOrdered')
                item['quantity_shipped'] = order_item.getvalue('QuantityShipped')
                if order_item.get('ShippingPrice'):
                    item['ship_price'] = order_item.get('ShippingPrice').getvalue('Amount')
                if order_item.get('ItemPrice'):
                    item['item_price'] = order_item.get('ItemPrice').getvalue('Amount')
                    item['currency_total_amount'] = self._backend.env['res.currency'].search(
                        [('name', '=', order_item.get('ItemPrice').getvalue('CurrencyCode'))]).id
                    item['price_unit'] = (float(item['item_price'])) / float(item['quantity_purchased'])
                order['lines'].append(item)

    def _list_orders_next_token(self, arguments, orders_api=None):
        token = arguments.get('NextToken')
        if not token:
            return

        if not orders_api:
            orders_api = Orders(backend=self._backend)

        response = orders_api.list_orders_by_next_token(token=token)

        orders = {}
        if response and response._response_dict and response._response_dict[response._rootkey] and response._response_dict[response._rootkey].get('Orders') and \
                response._response_dict[response._rootkey]['Orders'].get('Order'):
            # If the result have one item, the result is a dict, however if the result have more than one item the result is a list
            orders_dict = response._response_dict[response._rootkey]['Orders']['Order']
            orders_dict = orders_dict if isinstance(orders_dict, list) else [orders_dict]
            for order in orders_dict:
                aux = self._get_order_data_from_dict(order)
                if aux:
                    orders[aux['order_id']] = aux

            if response._response_dict[response._rootkey].get('NextToken'):
                new_orders = self._list_orders_next_token(arguments={'NextToken':response._response_dict[response._rootkey]['NextToken']['value']},
                                                          orders_api=orders_api)
                orders.update(new_orders)

        return orders

    def _list_orders(self, arguments):
        try:
            orders_api = Orders(backend=self._backend)
            marketplace_ids = arguments.get('marketplace_ids') or self._backend._get_crypt_codes_marketplaces()
            order_status = None
            date_start = None
            date_end = None
            last_update_start = None
            last_update_end = None
            if arguments:
                if arguments.get('date_start'):
                    date_start = arguments['date_start']
                if arguments.get('date_end'):
                    date_end = arguments['date_end']
                if arguments.get('update_start'):
                    last_update_start = arguments['update_start']
                if arguments.get('update_end'):
                    last_update_end = arguments['update_end']
                if arguments.get('order_status'):
                    order_status = arguments['order_status']

            if not order_status:
                order_status = arguments.get('order_status') or self._backend.env['amazon.config.order.status'].search([]).mapped('name')

            response = orders_api.list_orders(marketplaceids=marketplace_ids,
                                              orderstatus=order_status,
                                              created_before=date_end,
                                              created_after=date_start,
                                              lastupdatedbefore=last_update_end,
                                              lastupdatedafter=last_update_start)
            orders = {}
            if response and response._response_dict and response._response_dict[response._rootkey] and response._response_dict[response._rootkey].get(
                    'Orders') and \
                    response._response_dict[response._rootkey]['Orders'].get('Order'):
                # If the result have one item, the result is a dict, however if the result have more than one item the result is a list
                orders_dict = response._response_dict[response._rootkey]['Orders']['Order']
                orders_dict = orders_dict if isinstance(orders_dict, list) else [orders_dict]
                for order in orders_dict:
                    aux = self._get_order_data_from_dict(order)
                    if aux:
                        orders[aux['order_id']] = aux

                if response._response_dict[response._rootkey].get('NextToken'):
                    new_orders = self._list_orders_next_token(arguments={'NextToken':response._response_dict[response._rootkey]['NextToken']['value']},
                                                              orders_api=orders_api)

                    orders.update(new_orders)

            return orders
        except Exception as e:
            raise e

    def _get_order(self, order_ids, with_items=True):
        orders_api = Orders(backend=self._backend)
        orders = []
        try:
            if not isinstance(order_ids, (list, tuple)):
                order_ids = (order_ids)
            response = orders_api.get_order(amazon_order_ids=order_ids)
            if response and response._response_dict and response._response_dict[response._rootkey] and \
                    response._response_dict[response._rootkey].get('Orders') and response._response_dict[response._rootkey]['Orders'].get('Order'):
                orders_dict = response._response_dict[response._rootkey]['Orders']['Order']
                orders_dict = orders_dict if isinstance(orders_dict, list) else [orders_dict]
                for order_dict in orders_dict:
                    orders.append(self._get_order_data_from_dict(order_dict, with_items=with_items))

                if len(orders) > 1:
                    return orders
                elif len(orders) == 1:
                    return orders[0]


        except Exception as e:
            _logger.error("Getting order from order_api (%s) failed with id_order %s", '_get_order', str(order_ids))
            raise e

    @api.model
    def _get_header_product_fieldnames(self, marketplace):
        '''
        Method
        The csv fieldsnames for products is not equal in all marketplaces
        In Europe, we have the same configuration to all marketplaces except France
        :return: fieldnames for csv of products
        '''
        # TODO create a map with the headers
        if marketplace.country_id.code == 'FR':
            return [
                'title',
                'identifier_listing',
                'sku',
                'price',
                'quantity',
                'date_created',
                'type_identifier',
                'note',
                'product_state',
                'international_ship',
                'urgent_ship',
                'identifier_product',
                '',
                'fullfield_chanel',
                'merchant-shipping-group',
                'status',
            ]
        return [
            'title',
            'description',
            'identifier_listing',
            'sku',
            'price',
            'quantity',
            'date_created',
            '',
            'product_for_sell',
            'type_identifier',
            '',
            'note',
            'product_state',
            '',
            '',
            '',
            'asin',
            '',
            '',
            'international_ship',
            'urgent_ship',
            '',
            'identifier_product',
            '',
            'add_or_delete',
            'pending_qty',
            'fullfield_chanel',
            'merchant-shipping-group',
            'status',
        ]

    def _get_data_report(self, report_id, headers):
        try:
            assert report_id
        except AssertionError as e:
            _logger.error("report_api('%s') failed", '_get_data_report.report_id')
            raise e

        try:
            assert headers
        except AssertionError as e:
            _logger.error("report_api('%s') failed", '_get_data_report.headers')
            raise e

        rep_list_id = self._get_report_list_ids(report_id)
        # If there isn't the rep_list_id, we assume that there aren't data and the report had not been created
        if rep_list_id:
            response = self._get_report(report_list_id=rep_list_id)
            assert response
            if response:
                file = StringIO.StringIO()
                file.write(response.response.content)
                file.seek(0)
                reader = unicodecsv.DictReader(
                    file, fieldnames=headers,
                    delimiter='\t', quoting=False,
                    encoding=response.response.encoding)
                reader.next()  # we pass the file header
                return (response.response.encoding, reader)
            return

    def _get_feed_response(self, feed_id):
        feeds_api = Feeds(backend=self._backend)

        try:
            response = feeds_api.get_feed_submission_result(feedid=feed_id)
            if response and response.response and response.response.status_code == 200:
                return response
        except Exception as e:
            _logger.error("feeds_api(%s) failed with feed_ids %s", '_get_feed_result ', feed_id)
            raise e

    def _get_result_feed(self, feed_id, headers):
        try:
            assert feed_id
        except AssertionError as e:
            _logger.error("feed_api('%s') failed", '_get_result_feed.feed_id')
            raise e

        try:
            assert headers
        except AssertionError as e:
            _logger.error("feed_api('%s') failed", '_get_result_feed.headers')
            raise e

        response = self._get_feed_response(feed_id=feed_id)
        assert response
        if response:
            file = StringIO.StringIO()
            file.write(response.response.content)
            file.seek(0)
            reader = unicodecsv.DictReader(
                file, fieldnames=headers,
                delimiter='\t', quoting=False,
                encoding=response.response.encoding)
            reader.next()  # we pass the file header
            return (response.response.encoding, reader)
        return

    def _save_feed_response(self, id_feed):
        """
        Method that get the result of feed and save this on database
        :param id_feed:
        :return:
        """
        report = None
        response = self._get_feed_response(id_feed)
        if response and hasattr(response, '_response_dict') and response._response_dict and response._response_dict.get(
                'Message') and response._response_dict.get('Message').get('ProcessingReport') \
                and response._response_dict.get('Message').get('ProcessingReport').StatusCode == 'Complete':
            report = response._response_dict.get('Message').get('ProcessingReport').ProcessingSummary

        elif response and hasattr(response, 'response') and response.response.status_code == 200:
            report = response
            split_report = response.response.content.split('\n')
            messages_processed = ''
            messages_successful = ''
            messages_error = ''
            messages_warning = ''

            for value in split_report:
                if 'procesados\t\t' in value:
                    messages_processed = value[value.index('procesados\t\t') + len('procesados\t\t'):]
                elif 'registros correctos\t\t' in value:
                    messages_successful = value[value.index('registros correctos\t\t') + len('registros correctos\t\t'):]

            setattr(report, 'MessagesProcessed', messages_processed)
            setattr(report, 'MessagesSuccessful', messages_successful)
            setattr(report, 'MessagesWithError', messages_error)
            setattr(report, 'MessagesWithWarning', messages_warning)
            setattr(report, 'value', response.response.content)

        if report:
            feed = self._backend.env['amazon.feed'].search([('id_feed_submision', '=', id_feed)])

            vals = {'feed_id':feed.id,
                    'messages_processed':report.MessagesProcessed,
                    'messages_successful':report.MessagesSuccessful,
                    'messages_werror':report.MessagesWithError,
                    'messages_wwarning':report.MessagesWithWarning,
                    'message':report.value,
                    }

            res = self._backend.env['amazon.feed.result'].create(vals)
            if res:
                feed.feed_result_id = res.id

        return

    def _get_headers_add_products_csv_result(self):
        return [
            'original-record-number',
            'sku',
            'error-code',
            'error-type',
            'error-message',
        ]

    def _get_result_add_products_csv(self, feed_id):
        self._get_result_feed(feed_id=feed_id, headers=self._get_headers_add_products_csv_result())

    def _check_type_identifier(self, identifier):
        '''
        Method that return a UPC, EAN or None based on type of identifier parameter
        :param identifier: Number of identifier used to get the format and return the type of this
        :return: type of identifier
        '''

        if not identifier:
            return

        bce = self._backend.env['barcode.nomenclature']
        bcp = self._backend.pool.get('barcode.nomenclature')

        type = ''
        if bcp.check_ean(bce, identifier):
            type = 'EAN'
        if bcp.check_encoding(bce, identifier, 'upca'):
            type = 'UPC'

        return type

    def _extract_info_product(self, data, marketplace, products):
        '''
        Method to extract the info of the product
        :param data: this param is a list, on the first position is the encoding and on the second position the data to extract
        :param marketplace: marketplace of the product
        :param products: dictionary with other products added before or not
        :return:
        '''
        if not products:
            products = {}

        encoding = data[0]
        reader = data[1]
        for line in reader:
            if not line.get('sku'):
                continue

            data_prod_market = self._get_product_market_data_line(encoding=encoding, marketplace=marketplace, line=line)
            name = data_prod_market['title']

            # If the product doesn't exist we get all data
            if not products.get(line['sku']):
                type_identifier = self._check_type_identifier(identifier=line['identifier_product'])
                identifier_product = line['identifier_product'] if type_identifier else None

                asin = ''
                if line.get('asin') or (not type_identifier and line.get('identifier_product')):
                    asin = line.get('asin') or line.get('identifier_product')

                products[line['sku']] = {
                    'sku':line['sku'],
                    'asin':asin,
                    'name':name,
                    'amazon_qty':line['quantity'],
                    'id_type_product':type_identifier,
                    'id_product':identifier_product,
                    'product_product_market_ids':[data_prod_market],
                    'marketplace_id':marketplace.id,
                }
            # If the product exist, only get the marketplace data
            else:
                products[line['sku']]['product_product_market_ids'].append(data_prod_market)
                if self._backend.region.id == marketplace.country_id.id:
                    products['name'] = name

        return products

    def _get_product_market_data_line(self, encoding, marketplace, line):

        date_created = self._get_odoo_datetime_format(line['date_created'.decode(encoding)])

        return {
            'sku':line['sku'],
            'title':line['title'.decode(encoding)],
            'price_unit':line['price'],
            'currency_price_unit':marketplace.country_id.currency_id.id,
            'currency_shipping':marketplace.country_id.currency_id.id,
            'stock':line['quantity'],
            'merchant_shipping_group':line['merchant-shipping-group'],
            'status':line['status'],
            'marketplace_id':marketplace.id,
            'lang_id':marketplace.lang_id.id,
            'date_created':date_created,
        }
        return

    def _get_header_feedback_fieldnames(self):
        return [
            'date',
            'qualification',
            'comments',
            'respond',
            'order-id',
            'customer-email',
        ]

    def _extract_info_feedbacks(self, data, feedbacks):
        # encoding = data[0]
        reader = data[1]
        if not feedbacks:
            feedbacks = {}
        for line in reader:
            if not feedbacks.get(line['order-id']):
                feedbacks[line['order-id']] = {'feedback_date':self._get_odoo_date_format(line['date']),
                                               'qualification':line['qualification'],
                                               'message':line['comments'],
                                               'respond':line['respond'],
                                               'amazon_sale_id':line['order-id'],
                                               'email':line['customer-email']}
        return feedbacks

    def _get_header_sales_fieldnames(self):
        return [
            'order-id',
            'order-item-id',
            'purchase-date',
            'payments-date',
            'buyer-email',
            'buyer-name',
            'buyer-phone-number',
            'sku',
            'product-name',
            'quantity-purchased',
            'currency',
            'item-price',
            'item-tax',
            'shipping-price',
            'shipping-tax',
            'ship-service-level',
            'ship-service-name',
            'recipient-name',
            'ship-address-1',
            'ship-address-2',
            'ship-address-3',
            'ship-city',
            'ship-state',
            'ship-postal-code',
            'ship-country',
            'ship-phone-number',
            'delivery-start-date',
            'delivery-end-date',
            'delivery-time-zone',
            'delivery-Instructions',
            'order-channel',
            'order-channel-instance',
            'external-order-id',
            'earliest-ship-date',
            'latest-ship-date',
            'earliest-delivery-date',
            'latest-delivery-date',
            'is-business-order',
            'purchase-order-number',
            'price-designation',
            'fulfilled-by',
            'shipment-status',
        ]

    def _extract_info_sales(self, data, sales, marketplace_id):
        # encoding = data[0]
        reader = data[1]
        if not sales:
            sales = {}
        for line in reader:
            if not line.get('order-item-id'):
                continue
            if line['order-id'] in sales:
                line_to_append = self._get_sale_line(line)
                line_to_append.update({'marketplace_id':marketplace_id})

                sales[line['order-id']]['lines'].append(line_to_append)
            else:
                line_to_append = self._get_sale_line(line)
                line_to_append.update({'marketplace_id':marketplace_id})

                sales[line['order-id']] = {
                    'order_id':line['order-id'],
                    'date_order':self._get_odoo_datetime_format(line['purchase-date']),
                    'currency':line['currency'],
                    'items_purchased':line['quantity-purchased'],
                    'earlest_ship_date':self._get_odoo_datetime_format(line['earliest-ship-date']),
                    'lastest_ship_date':self._get_odoo_datetime_format(line['latest-ship-date']),
                    'earlest_delivery_date':self._get_odoo_datetime_format(line['earliest-delivery-date']),
                    'lastest_delivery_date':self._get_odoo_datetime_format(line['latest-delivery-date']),
                    'ship_service_level':line['ship-service-level'],
                    'FulfillmentChannel':line['fulfilled-by'] or 'MFN',
                    'marketplace_id':marketplace_id,
                    'partner':{
                        'email':line['buyer-email'],
                        'alias':line['buyer-name'],
                        'name':line['recipient-name'],
                        'type':'delivery',
                        'phone':line['ship-phone-number'],
                        'street':line['ship-address-1'],
                        'street2':line['ship-address-2'],
                        'street3':line['ship-address-3'],
                        'city':line['ship-city'],
                        'state':line['ship-state'],
                        'zip':line['ship-postal-code'],
                        'country_id':line['ship-country'],
                        'marketplace_id':marketplace_id,
                    },
                    'lines':[line_to_append],
                }
        return sales

    def _get_sale_line(self, line):
        return {
            'id_item':line['order-item-id'],
            'sku':line['sku'],
            'name':'[%s] %s' % (line['sku'], line['product-name']),
            'product_uom_qty':line['quantity-purchased'],
            # price is tax included, vat is computed in odoo
            'price_unit':
                (float(line['item-price'])) \
                / float(line['quantity-purchased']),
            'item_price':line['item-price'],
            'quantity_purchased':line['quantity-purchased'],
            'ship_price':float(line['shipping-price']),
            'currency':line['currency'],
        }

    def _get_inventory(self, report_ids):
        try:
            assert report_ids
            products = {}
            for report_id in report_ids:
                marketplace = self._backend.env['amazon.config.marketplace'].search([('id_mws', '=', report_id[1])])
                data = self._get_data_report(report_id[0], headers=self._get_header_product_fieldnames(marketplace))
                if data:
                    # We will update products object inside the method
                    products = self._extract_info_product(data, marketplace, products)
            return products
        except AssertionError:
            _logger.error("api('%s', %s) failed", 'get_inventory', report_ids)
            raise FailedJobError("api('%s', %s) failed", 'get_inventory', report_ids)
        except:
            raise FailedJobError("api('%s', %s) failed", 'get_inventory', report_ids)

    def _get_sales(self, report_ids):
        assert report_ids
        sales = {}
        for report_id in report_ids:
            data = self._get_data_report(report_id[0], headers=self._get_header_sales_fieldnames())
            if data:
                sales = self._extract_info_sales(data=data, sales=sales, marketplace_id=report_id[1])
        return sales

    def _get_customer_feedbacks(self, report_ids):
        assert report_ids
        feedbacks = {}
        for report_id in report_ids:
            data = self._get_data_report(report_id[0], headers=self._get_header_feedback_fieldnames())
            if data:
                feedbacks = self._extract_info_feedbacks(data=data, feedbacks=feedbacks)
        return feedbacks

    def _amazon_sale_order_search(self, arguments):
        return self._list_orders(arguments=arguments)

    def _amazon_sale_order_read(self, arguments):
        return self._get_order(order_ids=arguments)

    def _amazon_product_product_read(self, arguments):
        return self._get_product_data(sku=arguments[0], marketplace_id=arguments[1])

    def _api(self, method, arguments):
        if method in AMAZON_SUBMIT_REPORT_METHOD_DICT.keys():
            return self._submit_report(method=method, arguments=arguments)
        elif method in AMAZON_METHOD_LIST:
            if arguments:
                return getattr(self, '_' + method)(*arguments)
            return getattr(self, '_' + method)()

    def call(self, method, arguments):
        try:
            assert method
        except AssertionError as ase:
            _logger.log(logging.DEBUG, 'The method on AmazonAPI call is empty %s', self.name)
            return ase

        try:
            return self._api(method, arguments)
        except MWSError as mwse:
            raise RetryableJobError('An error has been produced on MWS API', ignore_retry='RequestThrottled' in mwse.message, seconds=90)
        except Exception as e:
            _logger.error("api('%s', %s) failed", method, arguments)
            raise e


class AmazonCRUDAdapter(AbstractComponent):
    """ External Records Adapter for Amazon """

    _name = 'amazon.crud.adapter'
    _inherit = ['base.backend.adapter', 'base.amazon.connector']
    _usage = 'backend.adapter'

    def search(self, filters=None):
        """ Search records according to some criterias
        and returns a list of ids """
        raise NotImplementedError

    def read(self, id, attributes=None):
        """ Returns the information of a record """
        raise NotImplementedError

    def search_read(self, filters=None):
        """ Search records according to some criterias
        and returns their information"""
        raise NotImplementedError

    def create(self, data):
        """ Create a record on the external system """
        raise NotImplementedError

    def write(self, id, data):
        """ Update records on the external system """
        raise NotImplementedError

    def delete(self, id):
        """ Delete a record on the external system """
        raise NotImplementedError

    def _call(self, method, arguments):
        try:
            amazon_api = getattr(self.work, 'amazon_api')
        except AttributeError:
            raise AttributeError(
                'You must provide a amazon_api attribute with a '
                'AmazonAPI instance to be able to use the '
                'Backend Adapter.'
            )
        return amazon_api.call(method, arguments)


class GenericAdapter(AbstractComponent):
    _name = 'amazon.adapter'
    _inherit = 'amazon.crud.adapter'

    _amazon_model = None
    _admin_path = None

    def _get_model(self):
        if self._amazon_model:
            return self._amazon_model
        elif self.model:
            return self.model._name
        elif self._apply_on:
            return self._apply_on
        return ''

    def search(self, filters=None):
        """ Search records according to some criterias
        and returns a list of ids

        :rtype: list
        """
        return self._call('%s_search' % self._get_model().replace('.', '_'), [filters] if filters else [{}])

    def read(self, external_id, attributes=None):
        """ Returns the information of a record

        :rtype: dict
        """
        if external_id and isinstance(external_id, (list, tuple)):
            arguments = external_id
        else:
            arguments = [external_id]
        if attributes:
            arguments.append(attributes)
        return self._call('%s_read' % self._get_model().replace('.', '_'), [arguments])

    def search_read(self, filters=None):
        """ Search records according to some criterias
        and returns their information"""
        return self._call('%s_list' % self._get_model(), [filters])

    def create(self, data):
        """ Create a record on the external system """
        return self._call('%s_create' % self._get_model(), [data])

    def write(self, id, data):
        """ Update records on the external system """
        return self._call('%s_update' % self._get_model(),
                          [int(id), data])

    def delete(self, id):
        """ Delete a record on the external system """
        return self._call('%s.delete' % self._get_model(), [int(id)])
