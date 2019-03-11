# -*- coding: utf-8 -*-
# Copyright 2013-2017 Camptocamp SA
# © 2016 Sodexis
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import models, fields, api

from odoo import osv

_logger = logging.getLogger(__name__)

AMAZON_DEFAULT_PERCENTAGE = 15


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
    identifier = fields.Integer('Identifier', required=True)
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
