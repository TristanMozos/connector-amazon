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
import re

from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import mapping, only_create

_logger = logging.getLogger(__name__)


class PartnerImportMapper(Component):
    _name = 'amazon.partner.import.mapper'
    _inherit = 'amazon.import.mapper'
    _apply_on = 'amazon.res.partner'

    direct = [
        ('name', 'name'),
        ('alias', 'alias'),
        ('email', 'email'),
        ('phone', 'phone'),
        ('street', 'street'),
        ('street2', 'street2'),
        ('street3', 'street3'),
        ('city', 'city'),
        ('zip', 'zip'),
        ('type', 'type'),
    ]

    @only_create
    @mapping
    def lang(self, record):
        if record.get('marketplace_id'):
            market = self.env['amazon.config.marketplace'].search([('id_mws', '=', record['marketplace_id'])])
            if market:
                return {'lang':market.lang_id.code}
        return

    @mapping
    def country_id(self, record):
        if record.get('country_id'):
            country = self.env['res.country'].search([('code', '=', record['country_id'])])
            if country:
                return {'country_id':country.id}
        return

    @mapping
    def vat(self, record):
        if record.get('country_id'):
            street_string = (record.get('street') or '') + ' ' + (record.get('street2') or '') + ' ' + (record.get('street3') or '')
            split_street = re.sub(u'[^A-Za-z0-9ÁÉÍÓÚÀÈÌÒÙÄËÏÖÜÑáéíóúàèìòùäëïöüñ]+', ' ', street_string or '').split(' ')
            partner = self.env['res.partner']
            aux = ''
            for piece in split_street:
                if partner.simple_vat_check(record['country_id'].lower(), piece):
                    aux = record['country_id'].upper() + piece
                    break
                elif len(piece) > 1 and partner.simple_vat_check(record['country_id'].lower() or piece[:2].lower(), piece[2:]):
                    aux = record['country_id'].upper() or piece[:2].upper() + piece[2:]
                    break
            return {'vat':aux}

    @mapping
    def fiscal_position(self, record):
        '''
        It is done for spanish company
        This method calc the fiscal position of the partner considering the company is from Spain and the
        :param record:
        :return: property_account_position_id
        '''
        # TODO search a configuration or develop a module to map account_position with states of countries. When this is solve, remove the restriction for Spain

        company = None
        account_position = None

        company = self.env.user.company_id

        if company.country_id.code == 'ES' and record.get('country_id') and record.get('zip'):
            country_partner = self.env['res.country'].search([('code', '=', record['country_id'])])
            envfp = self.env['account.fiscal.position']

            if country_partner.code == 'ES':
                prov_zip = record['zip'][0:2] if len(record['zip']) > 1 else record['zip']

                if prov_zip == '35' or prov_zip == '38' or prov_zip == '51' or prov_zip == '52':
                    account_position = envfp.search([('name', '=', u'Régimen Extracomunitario / Canarias, Ceuta y Melilla')])
                else:
                    account_position = envfp.search([('name', '=', u'Régimen Nacional')])

            else:
                europe = self.env.ref('base.europe')
                if not europe:
                    europe = self.env["res.country.group"].search([('name', '=', 'Europe')], limit=1)

                if europe and country_partner and country_partner.id in europe.country_ids.ids:
                    account_position = envfp.search([('name', '=', u'Régimen Nacional')])
                else:
                    account_position = envfp.search([('name', '=', u'Régimen Extracomunitario / Canarias, Ceuta y Melilla')])

            if account_position:
                return {'property_account_position_id':account_position.id}
        return

    @mapping
    def state_id(self, record):
        if record.get('country_id') and record.get('state'):
            state = self.env['res.country.state'].search([('country_id.code', '=', record['country_id']), ('name', '=', record['state'])])
            if state:
                return {'state_id':state.id}
        return {'state_id':None}

    @only_create
    @mapping
    def is_company(self, record):
        # partners are companies so we can bind
        # addresses on them
        return {'is_company':False}

    @mapping
    def type(self, record):
        return {'type':'delivery'}

    @only_create
    @mapping
    def odoo_id(self, record):
        """ Will bind the customer on a existing partner
        with the same email """
        partner = self.env['res.partner'].search(
            [('email', '=', record['email']),
             ('zip', '=', record['zip']),
             '|',
             ('is_company', '=', True),
             ('parent_id', '=', False)],
            limit=1,
        )
        if partner:
            return {'odoo_id':partner.id}

    @mapping
    def backend_id(self, record):
        return {'backend_id':self.backend_record.id}


class PartnerImporter(Component):
    _name = 'amazon.res.partner.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.res.partner']

    def _get_amazon_data(self):
        return self.amazon_record
