# -*- coding: utf-8 -*-
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import boto3
from datetime import datetime, timedelta

from odoo import models, fields

DEFAULT_ROUND_MESSAGES_TO_PROCESS = '10'


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

    sqs_account_id = fields.Many2one(comodel_name='amazon.config.sqs.account')
    id_message = fields.Char(required=True)
    recept_handle = fields.Char(required=True)
    body = fields.Char(required=True)
    processed = fields.Boolean(default=False)
    sqs_deleted = fields.Boolean(default=False)
