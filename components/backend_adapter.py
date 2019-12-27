# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# This project is based on connector-magneto, developed by Camptocamp SA

import StringIO
import logging
import dateutil.parser
import re
from lxml import etree

import unicodecsv
from odoo.fields import Datetime
from odoo.addons.component.core import AbstractComponent
from odoo.addons.queue_job.exception import FailedJobError, RetryableJobError

from ..mws.mws import MWSError

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
                                    'submit_updated_sales_request':'_GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE_'}

AMAZON_METHOD_LIST = ['get_inventory',
                      'get_sales',
                      'get_products_for_id',
                      'list_items_from_order',
                      'get_category_product',
                      'get_my_price_product',
                      'get_lowest_price_and_buybox',
                      'get_offers_changed',
                      'amazon_sale_order_read',
                      'amazon_sale_order_search',
                      'amazon_product_product_read',
                      'submit_stock_update',
                      'submit_price_update',
                      'submit_stock_price_handling_update',
                      'submit_add_inventory_request',
                      'submit_stock_price_update',
                      ]


class AmazonAPI(object):

    def __init__(self, backend):
        self._backend = backend

    def __enter__(self, *args, **kwargs):
        return self

    def __exit__(self, *args, **kwargs):
        return self

    def _get_odoo_date_format(self, iso_date):
        if iso_date:
            try:
                str_date = Datetime.to_string(dateutil.parser.parse(iso_date))
                return str_date
            except:
                return ''
        return ''

    def _get_messages_of_sqs_account(self, sqs_account):
        get_more_messages = sqs_account._get_last_messages()
        if get_more_messages:
            self._get_messages_of_sqs_account(sqs_account)

    def _get_offers_changed(self):
        sqs_accounts = self._backend.env['amazon.config.sqs.account'].search([('backend_id', '=', self._backend.id)])
        if not sqs_accounts:
            _logger.info('There aren\'t sqs accounts configured for this backend (%s)' % self._backend.name)
        else:
            for sqs_account in sqs_accounts:
                self._get_messages_of_sqs_account(sqs_account)
        return

    def _save_feed(self, response, params, xml_csv):
        amz_feed = self._backend.env['amazon.feed']
        if response and response._response_dict and response._response_dict[response._rootkey] and response._response_dict[response._rootkey].get(
                'FeedSubmissionInfo'):
            info_feed = response._response_dict[response._rootkey].get('FeedSubmissionInfo')
            type_feed = [x[0] for x in amz_feed.get_feed_types() if x[1] == info_feed.getvalue('FeedType')]
            vals = {'id_feed_submision':info_feed.getvalue('FeedSubmissionId'),
                    'type':type_feed[0] if type_feed else '',
                    'submitted_date':info_feed.getvalue('SubmittedDate'),
                    'feed_processing_status':info_feed.getvalue('FeedProcessingStatus'),
                    'params':params.encode('utf8') if params else None,
                    'xml_csv':xml_csv.decode('utf8') if xml_csv else None,
                    'backend_id':self._backend.id}

            amz_feed.create(vals)
            return info_feed.getvalue('FeedSubmissionId')
        return

    def _submit_stock_update(self, arguments):
        feedsApi = Feeds(backend=self._backend)

        top = etree.Element('AmazonEnvelope')

        header = etree.SubElement(top, 'Header')
        docVersion = etree.SubElement(header, 'DocumentVersion')
        docVersion.text = '1.01'
        merchantId = etree.SubElement(header, 'MerchantIdentifier')
        merchantId.text = self._backend.token

        messageType = etree.SubElement(top, 'MessageType')
        messageType.text = 'Inventory'

        dict_products = arguments

        '''
        Dict structure
        dict_products = [{'sku': 'D5-0BJZ-39B4', 'Quantity': 2, 'id_mws':'A1RKKUPIHCS9HS'},
                         {'sku': 'CH-N74Z-DD0S', 'Quantity': 5,'id_mws':'A1RKKUPIHCS9HS'},
                         {'sku': '9P-NBB6-095H', 'Quantity': 4, 'id_mws': 'A1RKKUPIHCS9HS'}]
        '''
        ids = []
        for market in self._backend.marketplace_ids:
            products = filter(lambda x:x['id_mws'] == market.id_mws, dict_products)  # Output: [{'name': 'python', 'points': 10}]

            i = 1

            for product in products:
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

            response = feedsApi.submit_feed(feed=xml,
                                            feed_type='_POST_INVENTORY_AVAILABILITY_DATA_',
                                            marketplaceids=[market.id_mws])

            ids.append({'id_feed':self._save_feed(response=response, params=str(arguments), xml_csv=xml) or 'Error',
                        'id_mws':market.id_mws})

        return ids

    def _submit_price_update(self, arguments):
        feedsApi = Feeds(backend=self._backend)

        top = etree.Element('AmazonEnvelope')

        header = etree.SubElement(top, 'Header')
        docVersion = etree.SubElement(header, 'DocumentVersion')
        docVersion.text = '1.01'
        merchantId = etree.SubElement(header, 'MerchantIdentifier')
        merchantId.text = self._backend.token

        messageType = etree.SubElement(top, 'MessageType')
        messageType.text = 'Price'

        dict_products = arguments

        '''
        Dict structure
        dict_products = [{'sku': 'D5-0BJZ-39B4', 'price': '84.80', currency:'EUR', 'id_mws':'A1RKKUPIHCS9HS'},
                         {'sku': 'CH-N74Z-DD0S', 'price': '24,45', currency:'EUR', 'id_mws':'A1RKKUPIHCS9HS'}]
        '''
        feed_ids = []
        for market in self._backend.marketplace_ids:
            products = filter(lambda x:x['id_mws'] == market.id_mws, dict_products)  # Output: [{'name': 'python', 'points': 10}]
            i = 1
            for product in products:
                message = etree.SubElement(top, 'Message')
                messageID = etree.SubElement(message, 'MessageID')
                messageID.text = int(i)

                operationType = etree.SubElement(message, 'OperationType')
                operationType.text = 'Update'

                price = etree.SubElement(message, 'Price')

                sku = etree.SubElement(price, 'SKU')
                sku.text = product['sku']
                standar_price = etree.SubElement(price, 'StandardPrice')
                standar_price.text = product['price']
                standar_price.set('currency', product['currency'])
                i += 1

            xml = etree.tostring(top, pretty_print=True, xml_declaration=True, encoding='UTF-8')

            xml = xml.replace('<AmazonEnvelope>',
                              '<AmazonEnvelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="amzn-envelope.xsd">')

            response = feedsApi.submit_feed(feed=xml,
                                            feed_type='_POST_PRODUCT_PRICING_DATA_',
                                            marketplaceids=[market.id_mws])

            feed_ids.append(self._save_feed(response=response, params=str(arguments), xml_csv=xml))

        return feed_ids

    def _submit_stock_price_update(self, arguments):
        """
        Send the csv file as it is described on https://s3.amazonaws.com/seller-templates/ff/eu/es/Flat.File.PriceInventory.es.xls
        :param arguments:
        :return:
        """
        feedsApi = Feeds(backend=self._backend)

        dict_products = arguments

        '''
        Dict structure
        dict_products = [{'sku': 'D5-0BJZ-39B4', 'price': '84.80', 'Quantity': 4, 'id_mws':'A1RKKUPIHCS9HS', 'handling_time':2},
                         {'sku': 'CH-N74Z-DD0S', 'price': '24,45', 'Quantity': 5, 'id_mws':'A1RKKUPIHCS9HS', 'handling_time':4}]
        '''
        feed_ids = []
        for market in self._backend.marketplace_ids:
            products = filter(lambda x:x['id_mws'] == market.id_mws, dict_products)  # Output: [{'name': 'python', 'points': 10}]

            if products:
                titles = ('sku', 'price', 'minimum-seller-allowed-price', 'maximum-seller-allowed-price', 'quantity', 'fulfillment-channel', 'leadtime-to-ship')
                csv = '\t'
                csv = csv.join(titles) + '\n'

                for product in products:
                    data = '\t'
                    product_data = (product.get('sku') or '', product.get('Price') or '', product.get('minimum-seller-allowed-price') or '',
                                    product.get('maximum-seller-allowed-price') or '', product.get('Quantity') or '0',
                                    product.get('fulfillment-channel') or '',
                                    product.get('handling-time') or '')
                    data = data.join(product_data) + '\n'
                    csv = csv + data

                response = feedsApi.submit_feed(feed=csv,
                                                feed_type='_POST_FLAT_FILE_PRICEANDQUANTITYONLY_UPDATE_DATA_',
                                                marketplaceids=[market.id_mws])

                feed_ids.append(self._save_feed(response=response, params=str(arguments), xml_csv=csv))

        return feed_ids

    def _submit_add_inventory_request(self, arguments):
        """
        Send a csv feed as it is described in https://s3.amazonaws.com/seller-templates/ff/eu/es/Flat.File.InventoryLoader.es.xls
        :param arguments:
        :return:
        """

        feedsApi = Feeds(backend=self._backend)

        dict_products = arguments

        '''
        Dict structure
        dict_products = [{'sku': 'D5-0BJZ-39B4', 'product-id-type': 'ASIN', 'product-id': 'B31N70DRX0', 'item-condition': '11', 'price': '84,80', 'Quantity': 4, 'id_mws':'A1RKKUPIHCS9HS', 'handling_time':2},
                         {'sku': 'CH-N74Z-DD0S', 'product-id-type': 'ASIN', 'product-id': 'B44S70ERQA', 'item-condition': '11', 'price': '24,45', 'Quantity': 5, 'id_mws':'A1RKKUPIHCS9HS', 'handling_time':4}]
        '''
        feed_ids = []
        for market in self._backend.marketplace_ids:
            products = filter(lambda x:x['id_mws'] == market.id_mws, dict_products)  # Output: [{'name': 'python', 'points': 10}]

            if products:
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
                csv = '\t'
                csv = csv.join(titles) + '\n'

                for product in products:
                    data = '\t'
                    product_data = (product.get('sku') or '', product.get('product-id') or '', product.get('product-id-type') or '', product.get('price') or '',
                                    product.get('minimum-seller-allowed-price') or '', product.get('maximum-seller-allowed-price') or '',
                                    product.get('item-condition') or '',
                                    product.get('quantity') or '', product.get('add-delete') or '', product.get('will-ship-internationally') or '',
                                    product.get('expedited-shipping') or '', product.get('item-note') or '', product.get('merchant-shipping-group-name') or '',
                                    product.get('product_tax_code') or '', product.get('fulfillment_center_id') or '', product.get('handling-time') or '',
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
                    csv = csv + data

                response = feedsApi.submit_feed(feed=csv,
                                                feed_type='_POST_FLAT_FILE_INVLOADER_DATA_',
                                                marketplaceids=[market.id_mws])

                feed_ids.append(self._save_feed(response=response, params=str(arguments), xml_csv=csv))

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
                    offer['feedback_rating'] = aux['SellerFeedbackRating'].getvalue('SellerPositiveFeedbackRating')
                    offer['ship_price'] = aux['Shipping'].getvalue('Amount')
                    offer['ship_currency'] = aux['Shipping'].getvalue('CurrencyCode')
                    offer['price'] = aux['ListingPrice'].getvalue('Amount')
                    offer['currency_price'] = aux['ListingPrice'].getvalue('CurrencyCode')
                    offer['max_hours_ship'] = aux['ShippingTime'].getvalue('maximumHours')
                    offer['min_hours_ship'] = aux['ShippingTime'].getvalue('minimumHours')
                    offer['country_ship_from'] = aux['ShipsFrom'].getvalue('Country') if aux.get('ShipsFrom') else ''
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
            response = product_api.get_matching_product_for_id(type='SellerSKU', ids=[sku], marketplaceid=marketplace_id)

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

    def _get_my_estimate_fee(self, marketplace_id, type_sku_asin, id_type, price, currency, ship_price, currency_ship, product_api=None):
        if not product_api:
            product_api = Products(backend=self._backend)

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
        order['date_order'] = self._get_odoo_date_format(order_dict.getvalue('PurchaseDate'))
        order['earlest_ship_date'] = self._get_odoo_date_format(order_dict.getvalue('EarliestShipDate'))
        order['lastest_ship_date'] = self._get_odoo_date_format(order_dict.getvalue('LatestShipDate'))
        order['earlest_delivery_date'] = self._get_odoo_date_format(order_dict.getvalue('EarliestDeliveryDate'))
        order['lastest_delivery_date'] = self._get_odoo_date_format(order_dict.getvalue('LatestDeliveryDate'))
        order['order_status_id'] = self._backend.env['amazon.config.order.status'].search([('name', '=', order_dict.getvalue('OrderStatus'))]).id
        order['is_prime'] = order_dict.getvalue('IsPrime')
        order['is_premium'] = order_dict.getvalue('IsPremiumOrder')
        order['is_business'] = order_dict.getvalue('IsBusinessOrder')
        order['shipment_service_level_category'] = order_dict.getvalue('ShipmentServiceLevelCategory')
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
        except AssertionError, e:
            _logger.error("report_api('%s') failed", '_get_data_report.report_id')
            raise e

        try:
            assert headers
        except AssertionError, e:
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
            try:
                fee = self._get_my_estimate_fee(marketplace_id=marketplace.id_mws,
                                                type_sku_asin='SellerSKU',
                                                id_type=data_prod_market['sku'],
                                                price=data_prod_market['price_unit'],
                                                currency=data_prod_market['currency_price_unit'])
                if fee:
                    data_prod_market['fee'] = fee
            except Exception as e:
                _logger.error("Recovering price's product from product_api (%s) failed with sku %s and marketplace %s",
                              'extract_info_product',
                              data_prod_market['sku'],
                              marketplace.name)
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

        date_created = self._get_odoo_date_format(line['date_created'.decode(encoding)])

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
                    'date_order':self._get_odoo_date_format(line['purchase-date']),
                    'currency':line['currency'],
                    'items_purchased':line['quantity-purchased'],
                    'earlest_ship_date':self._get_odoo_date_format(line['earliest-ship-date']),
                    'lastest_ship_date':self._get_odoo_date_format(line['latest-ship-date']),
                    'earlest_delivery_date':self._get_odoo_date_format(line['earliest-delivery-date']),
                    'lastest_delivery_date':self._get_odoo_date_format(line['latest-delivery-date']),
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
            raise RetryableJobError('A error has been produced on MWS API', ignore_retry='RequestThrottled' in mwse.message, seconds=90)
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
