# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import models, fields, api

from odoo import osv

_logger = logging.getLogger(__name__)

AMAZON_DEFAULT_PERCENTAGE_FEE = 15.0
AMAZON_DEFAULT_PERCENTAGE_MARGIN = 40.0
AMAZON_COSINE_NAME_MIN_VALUE = 0.20
AMAZON_NUMBER_MESSAGES_CHANGE_PRICE_RECOVER = 300
MAX_NUMBER_SQS_MESSAGES_TO_RECEIVE = 10


class AmazonConfiguration(models.TransientModel):
    _name = 'amazon.config.settings'
    _inherit = 'res.config.settings'


"""
    default_percentage_fee = fields.float(
        string='Percentage fee',
        help='Default percentage fee',
        default=15.0,
    )

    default_percentage_margin = fields.float(
        string='Percentage margin',
        help='Default percentage margin',
        default=AMAZON_DEFAULT_PERCENTAGE_MARGIN,
    )

    max_number_messages_change_price_recover = fields.Integer(
        string='Number messages to recover',
        help='The maximum number of messages from change price recover',
        default=AMAZON_NUMBER_MESSAGES_CHANGE_PRICE_RECOVER,
    )
"""


# Amazon marketplaces, auxiliar model
class AmazonMarketplace(models.Model):
    _name = 'amazon.config.marketplace'

    name = fields.Char('name', required=True)
    country_id = fields.Many2one('res.country', 'Country')
    id_mws = fields.Char('id_mws', required=True)
    lang_id = fields.Many2one('res.lang', 'Language')
    decimal_currency_separator = fields.Char('Separator for currency', default=',', required=True)


class AmazonOrderItemCondition(models.Model):
    _name = 'amazon.config.order.item.condition'
    identifier = fields.Integer('Identifier')
    name = fields.Char('name', required=True)


class AmazonOrderStatus(models.Model):
    _name = 'amazon.config.order.status'
    name = fields.Char('name', required=True)


class AmazonOrderStatusUpdatables(models.Model):
    _name = 'amazon.config.order.status.updatable'
    name = fields.Char('name', required=True)


class AmazonOrderLevelService(models.Model):
    _name = 'amazon.config.order.levelservice'
    name = fields.Char('name', required=True)


class AmazonProductCategory(models.Model):
    _name = 'amazon.config.product.category'

    name = fields.Char(required=True)
    market_id = fields.Many2one('amazon.config.marketplace', 'Marketplace')
    parent_category = fields.Many2one('amazon.config.product.category')


class AmazonProductType(models.Model):
    _name = 'amazon.config.product.type'
    identifier = fields.Integer('Identifier', required=True)
    name = fields.Char('name', required=True)


class AmazonBrandBan(models.Model):
    _name = 'amazon.brand.ban'
    _description = 'Amazon Brand Ban'

    backend_id = fields.Many2one('amazon.backend')
    brand_ban = fields.Many2one('product.brand')
