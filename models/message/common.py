# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2018 Halltic eSolutions S.L. (http://www.halltic.com)
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
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.o
#
##############################################################################
import boto3
import logging

from datetime import datetime
from xml.etree import cElementTree as ET

from odoo import models, fields, api
from odoo.addons.queue_job.job import job
from odoo.exceptions import MissingError

from ..fix_data.common import AMAZON_SAVE_OLD_HISTORIC_OFFERS

DEFAULT_ROUND_MESSAGES_TO_PROCESS = '10'

_logger = logging.getLogger(__name__)


class SQSAccount(models.Model):
    _name = 'amazon.config.sqs.account'

    backend_id = fields.One2many(comodel_name='amazon.backend',
                                 inverse_name='sqs_account_id')
    name = fields.Char('Name', required=True)
    access_key = fields.Char('Access key ID', required=True)
    secret_key = fields.Char('Secret access key', required=True)
    region = fields.Char('Name of region', required=True, help='It is a code of region on SQS, for example London is eu-west-2')
    queue_url = fields.Char('Url of the Queue', required=True)
    number_message_to_process = fields.Integer('Number of messages to process per each')
    message_ids = fields.One2many(comodel_name='amazon.config.sqs.message',
                                  inverse_name='sqs_account_id')

    def _get_last_messages(self, remove_messages=True):
        """
        Get message from sqs
        :return:
        """
        # Create SQS client
        if self:
            sqs = boto3.client('sqs',
                               aws_access_key_id=self.access_key,
                               aws_secret_access_key=self.secret_key,
                               region_name=self.region
                               )

            max_number_messages = 10

            # Receive message from SQS queue
            response = sqs.receive_message(
                QueueUrl=self.queue_url,
                AttributeNames=[
                    'SentTimestamp'
                ],
                MaxNumberOfMessages=max_number_messages,
                MessageAttributeNames=[
                    'All'
                ],
                VisibilityTimeout=0,
                WaitTimeSeconds=0
            )

            if response.get('Messages'):
                for message in response['Messages']:
                    sqs_env = self.env['amazon.config.sqs.message']
                    # We check if the message has been imported before
                    result = sqs_env.search_count([('id_message', '=', message['MessageId'])])
                    if not result:
                        # If the message is new
                        vals = {'id_message':message['MessageId'],
                                'recept_handle':message['ReceiptHandle'],
                                'body':message['Body'],
                                'sqs_account_id':self.id,
                                'sqs_deleted':remove_messages}
                        result = sqs_env.create(vals)
                    # We remove the message from sqs
                    if remove_messages and result:
                        sqs.delete_message(
                            QueueUrl=self.queue_url,
                            ReceiptHandle=message['ReceiptHandle']
                        )
            # Return if we have get the max number of messages available
            return len(response['Messages']) == max_number_messages

    def _remove_account_messages(self):
        """
        Method to remove message from sqs service of the account
        :return:
        """
        if self:
            sqs = boto3.client('sqs',
                               aws_access_key_id=self.access_key,
                               aws_secret_access_key=self.secret_key,
                               region_name=self.region
                               )

            messages = self.message_ids.filtered(lambda message:message.sqs_deleted == False)
            for message in messages:
                sqs.delete_message(
                    QueueUrl=self.queue_url,
                    ReceiptHandle=message.receipt_handle
                )
                message.sqs_deleted = True


class SQSMessage(models.Model):
    _name = 'amazon.config.sqs.message'
    _inherit = 'amazon.binding'
    _description = 'Amazon sqs message'

    sqs_account_id = fields.Many2one(comodel_name='amazon.config.sqs.account')
    id_message = fields.Char(required=True, index=True)
    recept_handle = fields.Char(required=True)
    body = fields.Char(required=True)
    processed = fields.Boolean(default=False)
    sqs_deleted = fields.Boolean(default=False)

    @api.multi
    def _get_messages_price_changes(self, backend):
        """
        Method call to SQS service to get messages
        On backend_adapter we are going to get messages and save this on odoo
        :param backend:
        :return:
        """
        with backend.work_on(self._name) as work:
            importer = work.component(model_name='amazon.product.product', usage='amazon.product.offers.import')
            messages = importer.run_get_offers_changed()
            if messages and messages[1]:
                for message in messages[1]:
                    delayable = self.with_delay(priority=6, eta=datetime.now())
                    filters = {'method':'process_price_message', 'message':message.id}
                    delayable.description = '%s.%s' % (self._name, 'process_price_message()')
                    delayable.process_price_message(filters)



    @job(default_channel='root.amazon.message')
    @api.model
    def get_sqs_messages(self, backend, filters=None):
        self._get_messages_price_changes(backend)


    @job(default_channel='root.amazon.message')
    @api.model
    def process_price_message(self, record):
        res = None
        if record.get('message'):
            message = self.env['amazon.config.sqs.message'].browse(record['message'])
            res = self._process_message(message)
        elif record.get('xml'):
            res = self._process_message(xml_message=record['xml'])
        if res and res.get('mess_processed') and res.get('product_details'):
            # TODO change prices
            for detail in res['product_details']:
                detail._change_price()
    
    @job(default_channel='root.amazon')
    @api.model
    def delete_old_historic_offer(self, filters):
        assert filters['product_detail_id']
        # We recover the historic offers than we want to save plus 10
        historic_offers = self.env['amazon.historic.product.offer'].search([('product_detail_id', '=', filters['product_detail_id'])], order='offer_date asc', limit=AMAZON_SAVE_OLD_HISTORIC_OFFERS+10)
        # we get the number of historic offers that we are search on ddbb
        historic_offer_len = len(historic_offers)
        # If we had recovered more historic offers than we want to save, we remove the first (historic with oldest date)
        if historic_offers and historic_offer_len > AMAZON_SAVE_OLD_HISTORIC_OFFERS:
            # We delete the last historic offer
            historic_offers[0:historic_offer_len-AMAZON_SAVE_OLD_HISTORIC_OFFERS].unlink()
            # If we recovered 10 historics more than we want to save, we create a new job to delete more historic offer of this product
            if historic_offer_len >= AMAZON_SAVE_OLD_HISTORIC_OFFERS+10:
                message_binding_model = self.env['amazon.config.sqs.message']
                delayable = message_binding_model.with_delay(priority=7, eta=datetime.now())
                vals = {'product_detail_id': filters['product_detail_id']}
                delayable.description = '%s.%s' % (self._name, 'delete_old_historic_offer()')
                delayable.delete_old_historic_offer(vals)

    @api.multi
    def _process_message(self, message=None, xml_message=None):
        # We are going to delete the same messages
        messages = None

        if message:
            try:
                messages = message.search([('id_message', '=', message.id_message)])
            except MissingError as e:
                return
            message_to_process = False
            has_been_processed = False
            message_ids_to_delete = []
            return_vals = {}
            # It is a control for duplicate messages
            if len(messages) > 1:
                for mess in messages:
                    if mess.processed:
                        has_been_processed = True
                        message_to_process = True
                    if mess.id != message.id:
                        message_ids_to_delete.append(mess.id)
            elif len(messages) == 1 and messages.processed:
                has_been_processed = True

            xml_message = message.body

        if not has_been_processed and xml_message:
            root = ET.fromstring(message.body)
            notification = root.find('NotificationPayload').find('AnyOfferChangedNotification')
            offer_change_trigger = notification.find('OfferChangeTrigger')
            if offer_change_trigger is not None:
                id_mws = offer_change_trigger.find('MarketplaceId').text if offer_change_trigger.find('MarketplaceId') is not None else None
                asin = offer_change_trigger.find('ASIN').text if offer_change_trigger.find('ASIN') != None else None
                return_vals['asin'] = asin
                return_vals['id_mws'] = id_mws
                products = self.env['amazon.product.product.detail'].search([('product_id.asin', '=', asin), ('marketplace_id.id_mws', '=', id_mws)])
                if products:
                    return_vals['product_details'] = products
                    for detail_prod in products:
                        marketplace = detail_prod.marketplace_id
                        # item_condition = offer_change_trigger.find('ItemCondition').text if offer_change_trigger.find('ItemCondition') != None else None
                        time_change = offer_change_trigger.find('TimeOfOfferChange').text if offer_change_trigger.find(
                            'TimeOfOfferChange') is not None else None
                        time_change = datetime.strptime(time_change, "%Y-%m-%dT%H:%M:%S.%fZ")

                        historic = self.env['amazon.historic.product.offer'].search([('offer_date', '=', time_change.isoformat(sep=' ')),
                                                                                     ('product_detail_id', '=', detail_prod.id)])

                        res = None
                        # If the message hasn't been processed
                        if not historic:

                            lowest_price = None
                            summary = notification.find('Summary')
                            lowest_prices = summary.find('LowestPrices')
                            if lowest_prices is not None and lowest_prices.find('LowestPrice'):
                                low_price = float('inf')
                                for prices in lowest_prices:
                                    if prices.find('LandedPrice'):
                                        aux = prices.find('LandedPrice').find('Amount').text
                                        if float(aux) < low_price:
                                            low_price = float(aux)
                                lowest_price = low_price

                            # We are going to get offer data
                            new_offers = []
                            for offer in root.iter('Offer'):
                                new_offer = {}
                                new_offer['id_seller'] = offer.find('SellerId').text
                                if new_offer['id_seller'] == detail_prod.product_id.backend_id.seller:
                                    new_offer['is_our_offer'] = True
                                new_offer['condition'] = offer.find('SubCondition').text
                                listing_price = offer.find('ListingPrice')
                                if listing_price:
                                    new_offer['price'] = listing_price.find('Amount').text
                                    new_offer['currency_price_id'] = self.env['res.currency'].search(
                                        [('name', '=', listing_price.find('CurrencyCode').text)]).id
                                shipping = offer.find('Shipping')
                                if shipping:
                                    new_offer['price_ship'] = shipping.find('Amount').text
                                    new_offer['currency_ship_price_id'] = self.env['res.currency'].search(
                                        [('name', '=', shipping.find('CurrencyCode').text)]).id

                                if float(new_offer.get('price') or 0 + new_offer.get('price_ship') or 0) == lowest_price:
                                    new_offer['is_lower_price'] = True

                                # min_hours = None
                                # max_hours = None
                                # shipping_time = offer.find('ShippingTime')
                                # if shipping_time:
                                #    max_hours = offer.find('ShippingTime').attrib['maximumHours'] if offer.find('ShippingTime').attrib.get('maximumHours') else None
                                #    min_hours = offer.find('ShippingTime').attrib['minimumHours'] if offer.find('ShippingTime').attrib.get('minimumHours') else None

                                seller_feedback = offer.find('SellerFeedbackRating')
                                if seller_feedback:
                                    new_offer['seller_feedback_rating'] = seller_feedback.find('SellerPositiveFeedbackRating').text
                                    new_offer['seller_feedback_count'] = seller_feedback.find('FeedbackCount').text

                                new_offer['amazon_fulffilled'] = offer.find('IsFulfilledByAmazon').text == 'true' if offer.find(
                                    'IsFulfilledByAmazon').text else False
                                new_offer['is_buybox'] = offer.find('IsBuyBoxWinner').text == 'true'

                                ship_from = offer.find('ShipsDomestically')
                                if ship_from and ship_from.text == 'true':
                                    new_offer['country_ship_id'] = marketplace.country_id.id
                                else:
                                    ship_from = offer.find('ShipsFrom').find('Country').text if offer.find('ShipsFrom') and offer.find('ShipsFrom').find(
                                        'Country') else None
                                    if ship_from:
                                        new_offer['country_ship_id'] = self.env['res.country'].search([('code', '=', ship_from)]).id

                                is_prime = offer.find('PrimeInformation')
                                if is_prime:
                                    is_prime = offer.find('PrimeInformation').find('IsPrime').text == 'true' if offer.find('PrimeInformation').find(
                                        'IsPrime') != None and offer.find('PrimeInformation').find('IsPrime').text else None
                                    new_offer['is_prime'] = is_prime

                                # We save the offer on historic register
                                new_offers.append((0, 0, new_offer))

                            # We save the offers on historic offer
                            res = self.env['amazon.historic.product.offer'].create({'offer_date':time_change,
                                                                                    'product_detail_id':detail_prod.id,
                                                                                    'offer_ids':new_offers,
                                                                                    'message_body':message.body})
                            historic_count = self.env['amazon.historic.product.offer'].search_count([('product_detail_id', '=', detail_prod.id)])
                            if historic_count > AMAZON_SAVE_OLD_HISTORIC_OFFERS:
                                message_binding_model = self.env['amazon.config.sqs.message']
                                delayable = message_binding_model.with_delay(priority=7, eta=datetime.now())
                                vals = {'product_detail_id':detail_prod.id}
                                delayable.description = '%s.%s' % (self._name, 'delete_old_historic_offer()')
                                delayable.delete_old_historic_offer(vals)

                        if res or historic:
                            message_to_process = True

        message_ids_to_processed = []
        if message_to_process:
            message_ids_to_processed.append(message.id)

        if message_ids_to_delete:
            product_binding_model = self.env['amazon.product.product']
            delayable = product_binding_model.with_delay(priority=4, eta=datetime.now())
            vals = {'method':'delete_sqs_messages',
                    'message_ids':message_ids_to_delete}
            delayable.description = '%s.%s' % (self._name, 'delete_sqs_messages()')
            delayable.export_record(message.sqs_account_id.backend_id, vals)

        message_ids_to_processed.extend(message_ids_to_delete)
        messages_to_process = self.env['amazon.config.sqs.message'].browse(message_ids_to_processed)
        if messages_to_process:
            messages_to_process.write({'processed':True})

        return_vals['mess_processed'] = message_to_process
        return return_vals
