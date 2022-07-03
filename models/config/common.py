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
##############################################################################

import logging

from odoo import models, fields, api

from odoo import osv

_logger = logging.getLogger(__name__)

AMAZON_DEFAULT_PERCENTAGE_FEE = 15.0


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
