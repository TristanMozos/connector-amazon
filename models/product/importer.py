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
import inspect
import logging
import os
import urllib.request
import base64
from datetime import datetime

from odoo import api
from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import mapping
from odoo.addons.connector.exception import InvalidDataError

_logger = logging.getLogger(__name__)


class ProductProductBatchImporter(Component):
    """
    Import the Amazon Products.
    """
    _name = 'amazon.product.product.batch.importer'
    _inherit = 'amazon.delayed.batch.importer'
    _apply_on = 'amazon.product.product'


class ProductImportMapper(Component):
    _name = 'amazon.product.product.import.mapper'
    _inherit = 'amazon.import.mapper'
    _apply_on = ['amazon.product.product']
    _map_child_usage = 'import.map.child.product.detail'

    direct = [('name', 'name'),
              ('asin', 'asin'),
              ('sku', 'sku'),
              ('sku', 'external_id'),
              ('sku', 'default_code'),
              ('amazon_qty', 'amazon_qty'),
              ('id_type_product', 'id_type_product'),
              ('id_product', 'id_product'),
              ('height', 'height'),
              ('length', 'length'),
              ('weight', 'weight'),
              ('width', 'width'),
              ('brand', 'brand'),
              ]

    children = [('product_product_market_ids', 'product_product_market_ids', 'amazon.product.product.detail'), ]

    @mapping
    def name(self, record):
        if not record.get('odoo_id'):
            return {'name':record['name'] if len(record['name']) < 159 else record['name'][:160]}

    @mapping
    def backend_id(self, record):
        return {'backend_id':self.backend_record.id}

    @mapping
    def odoo_id(self, record):
        if record.get('odoo_id') and not record.get('id_product'):
            return {'odoo_id':record['odoo_id']}
        return None

    @mapping
    def barcode(self, record):
        if record.get('id_product'):
            prod_barcode = self.env['product.template'].search([('barcode', '=', record['id_product'])])
            if prod_barcode:
                return {'odoo_id':prod_barcode.product_variant_id.id}
            else:
                return {'barcode':record['id_product']}
        return None


class ImportMapChildProductDetail(Component):
    """ :py:class:`MapChild` for the Imports """

    _name = 'product.detail.map.child.import'
    _inherit = 'base.map.child'
    _usage = 'import.map.child.product.detail'

    def _child_mapper(self):
        """ Mandatory """
        return self.component(usage='import.mapper')

    def format_items(self, items_values):
        """ Format the values of the items mapped from the child Mappers.

        It can be overridden for instance to add the Odoo
        relationships commands ``(6, 0, [IDs])``, ...

        As instance, it can be modified to handle update of existing
        items: check if an 'id' has been defined by
        :py:meth:`get_item_values` then use the ``(1, ID, {values}``)
        command

        :param items_values: list of values for the items to create
        :type items_values: list

        """
        values = []
        for item in items_values:
            detail = self.env['amazon.product.product.detail'].search([('product_id.sku', '=', item['sku']), ('marketplace_id', '=', item['marketplace_id'])])
            if detail:
                if item['price_ship'] != False:
                    values.append((1, detail.id, {'status':item['status'],
                                                  'stock':item['stock'],
                                                  'price':item['price'],
                                                  'price_ship':item['price_ship'],
                                                  'merchant_shipping_group':item['merchant_shipping_group']}))
                else:
                    values.append((1, detail.id, {'status':item['status'],
                                                  'stock':item['stock'],
                                                  'price':item['price'],
                                                  'merchant_shipping_group':item['merchant_shipping_group']}))
            else:
                values.append((0, 0, item))

        return values


class ProductImporter(Component):
    _name = 'amazon.product.product.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.product.product']

    def _get_amazon_data(self):
        _logger.info('connector_amazon [%s][%s] log: Get amazon data' % (os.getpid(), inspect.stack()[0][3]))
        """ Return the raw Amazon data for ``self.external_id`` """
        if self.amazon_record:
            return self.amazon_record

        _logger.info('connector_amazon [%s][%s] log: There aren\'t data for the product %s we are going to get from Amazon' %
                     (self.external_id, os.getpid(), inspect.stack()[0][3]))
        product = {'sku':self.external_id}
        default_market = self.backend_record._get_marketplace_default()
        product['marketplace_id'] = default_market.id

        # We are going to recover all data
        for market in self.backend_record.marketplace_ids:
            data_market = self.backend_adapter.read(external_id=self.external_id, attributes=market.id_mws)
            if data_market:
                data_market['sku'] = self.external_id
                data_market['marketplace_id'] = market.id
                if product.get('product_product_market_ids'):
                    product['product_product_market_ids'].append(data_market)
                else:
                    product['product_product_market_ids'] = [data_market]
                    product['name'] = data_market['title']

                # Get ASIN from the first market with data
                if not product.get('asin'):
                    _logger.info('connector_amazon [%s][%s] log: Get amazon data to get ASIN' % (os.getpid(), inspect.stack()[0][3]))
                    data_product = self.backend_adapter.get_products_for_id(arguments=[[self.external_id],
                                                                                       market.id_mws,
                                                                                       'SellerSKU'])
                    product['asin'] = data_product[0]['asin'] if data_product else ''

                if default_market.id == market.id:
                    product['name'] = data_market['title']

        # If I need to explain you the sense of the next code I would have to kill you
        if product.get('product_product_market_ids'):
            market_match = map(lambda x:x['marketplace_id'] == product['marketplace_id'], product['product_product_market_ids'])
            if not market_match and product.get('product_product_market_ids'):
                product['marketplace_id'] = product['product_product_market_ids'][0]['marketplace_id']
        if product.get('marketplace_id'):
            product['marketplace'] = self.env['amazon.config.marketplace'].browse(product['marketplace_id'])

        return product

    def _before_import(self):
        """
        We need test if the product is on odoo
        :return:
        """
        # If there is a product that match default_code with sku we will link the product of odoo with new amazon product
        products = self.env['product.product'].search([('default_code', '=like', self.amazon_record['sku'])])

        # We link the products with the same amazon.sku and odoo.default_code
        if products:
            self.amazon_record['odoo_id'] = products[0].id

    def _get_binary_image(self, image_url):
        # TODO test this
        url = image_url.encode('utf8')
        try:
            response = urllib.request.urlopen(url)
        except urllib.request.HTTPError as err:
            if err.code == 404:
                # the image is just missing, we skip it
                return
            else:
                # we don't know why we couldn't download the image
                # so we propagate the error, the import will fail
                # and we have to check why it couldn't be accessed
                raise
        else:
            return response.read()

    def _write_brand(self, binding, product_data):
        if binding.product_tmpl_id.product_brand_id and product_data.get('brand') and \
                binding.product_tmpl_id.product_brand_id.name != product_data.get('brand'):
            brand = self.env['product.brand'].search([('name', '=', product_data['brand'])])
            if not brand:
                result = self.env['product.brand'].create({'name':product_data['brand']})
                product_data['product_brand_id'] = result.id
            else:
                product_data['product_brand_id'] = brand[0].id

            binding.product_tmpl_id.write({'product_brand_id':product_data.get('product_brand_id')})
            binding.write({'brand':product_data['brand']})

    def _write_dimensions(self, binding, product_data):

        ept = self.env['product.template']
        ppt = ept.pool.get('product.template')
        epu = self.env['amazon.uom.uom']

        if product_data.get('height') and not binding.product_tmpl_id.height:
            # If we have height from amazon, we import the value in meters
            try:
                if isinstance(product_data['height'], dict):
                    amaz_h_units = product_data['height'].getvalue('Units').lower()
                    height_units = epu.search([('name', '=', amaz_h_units)])
                    product_data['height'] = ppt.convert_to_meters(ept,
                                                                   float(product_data['height'].value),
                                                                   height_units.product_uom_id)
                binding.write({'height':product_data['height']})
                binding.product_tmpl_id.write({'height':product_data['height']})
            except:
                _logger.error("Getting height to import %s", binding.sku)

        if product_data.get('length') and not binding.product_tmpl_id.length:
            # If we have length from amazon, we import the value in meters
            try:
                if isinstance(product_data['length'], dict):
                    amaz_l_units = product_data['length'].getvalue('Units').lower()
                    length_units = epu.search([('name', '=', amaz_l_units)])
                    product_data['length'] = ppt.convert_to_meters(ept,
                                                                   float(product_data['length'].value),
                                                                   length_units.product_uom_id)
                binding.write({'length':product_data['length']})
                binding.product_tmpl_id.write({'length':product_data['length']})
            except:
                _logger.error("Getting length to import %s", binding.sku)

        if product_data.get('width') and not binding.product_tmpl_id.width:
            # If we have width from amazon, we import the value in meters
            try:
                if isinstance(product_data['width'], dict):
                    amaz_w_units = product_data['width'].getvalue('Units').lower()
                    width_units = epu.search([('name', '=', amaz_w_units)])
                    product_data['width'] = ppt.convert_to_meters(ept,
                                                                  float(product_data['width'].value),
                                                                  width_units.product_uom_id)
                binding.write({'width':product_data['width']})
                binding.product_tmpl_id.write({'width':product_data['width']})
            except:
                _logger.error("Getting wight to import: %s ", binding.sku)

        if product_data.get('weight') and not binding.product_tmpl_id.weight:
            try:
                if isinstance(product_data['weight'], dict):
                    amaz_w_units = product_data['weight'].getvalue('Units').lower()
                    weight_units = epu.search([('name', '=', amaz_w_units)])
                    if weight_units and weight_units.product_uom_id.uom_type != 'reference':
                        weight_reference = self.env['uom.uom'].search(
                            [('category_id', '=', weight_units.product_uom_id.category_id.id), ('uom_type', '=', 'reference')])
                        product_data['weight'] = weight_units.product_uom_id._compute_quantity(qty=float(product_data['weight'].value),
                                                                                               to_unit=weight_reference)
                    else:
                        product_data['weight'] = weight_units.product_uom_id._compute_quantity(qty=float(product_data['weight'].value),
                                                                                               to_unit=weight_units.product_uom_id)

                binding.write({'weight':product_data['weight']})
                binding.product_tmpl_id.write({'weight':product_data['weight']})
            except:
                _logger.error("Getting weight to import %s", binding.sku)

        return product_data

    def _write_image_data(self, binding, binary):
        binding = binding.with_context(connector_no_export=True)
        binding.write({'image':base64.b64encode(binary)})

    def _write_product_data(self, binding, marketplace):
        """
        We get the data from MWS and complete brand, dimenions and images of the product
        :param binding:
        :param marketplace:
        :return:
        """
        self.external_id = binding.external_id
        no_has_brand = not binding.odoo_id.product_brand_id
        no_has_dimensions = not (binding.odoo_id.height or binding.odoo_id.length or binding.odoo_id.width or binding.odoo_id.weight)
        no_has_images = not (binding.odoo_id.image_ids)
        if no_has_brand or no_has_dimensions or no_has_images:
            data_product = self.backend_adapter.read(external_id=self.external_id, attributes=marketplace.id_mws)

        # If we have the brand we do not need to update this
        if no_has_brand:
            self._write_brand(binding, data_product)
        # If we have the dimensions we do not need to update this
        if no_has_dimensions:
            self._write_dimensions(binding, data_product)
        if no_has_images:
            if data_product.get('url_images'):
                images = data_product['url_images']
                while images:
                    image_url = images.pop()
                    binary = self._get_binary_image(image_url)
                    self._write_image_data(binding, binary)

    def _validate_product_type(self, data):
        """ Check if the product type is in the selection (so we can
        prevent the `except_orm` and display a better error message).
        """
        product_type = data['product_type']
        product_model = self.env['amazon.product.product']
        types = product_model.product_type_get()
        available_types = [typ[0] for typ in types]
        if product_type not in available_types:
            raise InvalidDataError("The product type '%s' is not "
                                   "yet supported in the connector." %
                                   product_type)

    def _must_skip(self):
        """ Hook called right after we read the data from the backend.

        If the method returns a message giving a reason for the
        skipping, the import will be interrupted and the message
        recorded in the job (if the import is called directly by the
        job, not by dependencies).

        If it returns None, the import will continue normally.

        :returns: None | str | unicode
        """
        if not self.amazon_record.get('sku') or not self.amazon_record.get('name'):
            return 'The product can\'t be imported %s' % self.amazon_record['sku'] if self.amazon_record.get('sku') else ''

    def _validate_data(self, data):
        """ Check if the values to import are correct

        Pro-actively check before the ``_create`` or
        ``_update`` if some fields are missing or invalid

        Raise `InvalidDataError`
        """
        if not data or not data.get('name'):
            raise InvalidDataError

    def _create(self, data):
        """

        :param data:
        :return:
        """
        data['type'] = 'product'
        binding = super(ProductImporter, self)._create(data)
        return binding

    def _after_import(self, binding):
        """ Hook called at the end of the import """
        if self.amazon_record and self.amazon_record.get('marketplace_id'):
            self._write_product_data(binding, self.amazon_record.get('marketplace'))

        binding.product_tmpl_id.write({'is_amazon_product':True})

    def run(self, external_id, force=False):
        """ Run the synchronization

        :param external_id: identifier of the record on Amazon
        """
        if isinstance(external_id, (list, tuple)) and len(external_id) > 1:
            self.external_id = external_id[0].encode('utf8')
            self.amazon_record = external_id[1]
            if self.amazon_record and self.amazon_record.get('marketplace_id'):
                self.amazon_record['marketplace'] = self.env['amazon.config.marketplace'].browse(self.amazon_record['marketplace_id'])
                self.amazon_record['marketplace_name'] = self.amazon_record['marketplace'].name
        else:
            self.external_id = external_id.encode('utf8')

        _super = super(ProductImporter, self)
        return _super.run(external_id=self.external_id, force=force)


class ProductProductMarketImportMapper(Component):
    _name = 'amazon.product.product.detail.mapper'
    _inherit = 'amazon.import.mapper'
    _apply_on = 'amazon.product.product.detail'

    direct = [('title', 'title'),
              ('price_unit', 'price'),
              ('price_shipping', 'price_ship'),
              ('status', 'status'),
              ('stock', 'stock'),
              ('is_mine_buy_box', 'has_buybox'),
              ('is_mine_lowest_price', 'has_lowest_price'),
              ('lowest_landed_price', 'lowest_price'),
              ('lowest_listing_price', 'lowest_product_price'),
              ('lowest_shipping_price', 'lowest_shipping_price'),
              ('merchant_shipping_group', 'merchant_shipping_group'), ]

    @mapping
    def sku(self, record):
        return {'sku':record.get('sku')}

    @mapping
    def marketplace_id(self, record):
        return {'marketplace_id':record.get('marketplace_id')}

    @mapping
    def currency_id(self, record):
        if record.get('currency_price_unit') and isinstance(record['currency_price_unit'], float):
            return {'currency_id':record['currency_price_unit']}
        else:
            rce = self.env['res.currency']
            return {'currency_id':rce.search([('name', '=', record.get('currency_price_unit'))]).id or \
                                  self.env.user.company_id.currency_id.id or \
                                  self.env.ref('base.EUR').id}
        return

    @mapping
    def currency_price(self, record):
        if record.get('currency_price_unit') and isinstance(record['currency_price_unit'], float):
            return {'currency_price':record['currency_price_unit']}
        else:
            rce = self.env['res.currency']
            return {'currency_price':rce.search([('name', '=', record.get('currency_price_unit'))]).id or \
                                     self.env.user.company_id.currency_id.id or \
                                     self.env.ref('base.EUR').id}
        return

    @mapping
    def currency_ship(self, record):
        if record.get('currency_shipping') and isinstance(record['currency_shipping'], float):
            return {'currency_ship_price':record['currency_shipping']}
        else:
            rce = self.env['res.currency']
            return {'currency_ship_price':rce.search([('name', '=', record.get('currency_shipping'))]).id or \
                                          self.env.user.company_id.currency_id.id or \
                                          self.env.ref('base.EUR').id}
        return

    @mapping
    def total_fee(self, record):
        if record.get('fee'):
            return {'total_fee':record['fee']['Final']}

    @mapping
    def percentage_fee(self, record):
        if record.get('fee') and record.get('price_unit'):
            return {'percentage_fee':round((record['fee']['Amount'] * 100) / (float(record['price_unit']) + float(record.get('price_shipping') or 0)))}


class ProductDetailImporter(Component):
    _name = 'amazon.product.product.detail.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.product.product.detail']

    def run(self, external_id, force=False):
        """ Run the synchronization

        :param external_id: identifier of the record on Amazon
        """
        if isinstance(external_id, (list, tuple)):
            self.external_id = external_id[0]
            self.amazon_record = external_id[1]
        else:
            self.external_id = external_id
        _super = super(ProductDetailImporter, self)
        return _super.run(external_id=external_id[0], force=force)


class ProductLowestPriceImporter(Component):
    """ Import data for a record.

        Usually called from importers, in ``_after_import``.
        For instance from the products importer.
    """

    _name = 'amazon.product.offers.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.product.product']
    _usage = 'amazon.product.offers.import'

    def run(self, record):
        '''
        This method is called for get the lowest price, buybox, etc and the category of the product on the marketplace
        We get the data and we update only the data of the marketplace selected
        :param binding:
        :return:
        '''
        try:
            if record.marketplace_id:
                data = self.backend_adapter.get_lowest_price([record.product_id.sku, record.marketplace_id.id_mws])
                if data:
                    self._get_product_offers(record, data)
        except Exception as e:
            raise e

    @api.model
    def run_get_offers_changed(self):
        return self.backend_adapter.get_offers_changed()

    def run_offers_delete(self, offer_ids={}):
        if offer_ids:
            self.env['amazon.historic.product.offer'].browse(offer_ids).unlink()


class ProductPriceImporter(Component):
    """ Import data for a record.

        Usually called from importers, in ``_after_import``.
        For instance from the products importer.
    """

    _name = 'amazon.product.price.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.product.product']
    _usage = 'amazon.product.price.import'

    def run_update_price(self, detail):
        prices = self.run_get_price(detail)
        if prices:
            vals = {}
            price_unit = float(prices.get('price_unit') or 0.)
            price_ship = float(prices.get('price_shipping') or 0.)
            vals['price'] = price_unit
            vals['price_ship'] = price_ship
            if prices.get('fee'):
                vals['percentage_fee'] = round((prices['fee']['Amount'] * 100) / (price_unit + price_ship or 0))
                vals['total_fee'] = prices['fee']['Final']
            # If there are changes on prices or fee we are going to update this
            if vals and (
                    (vals.get('percentage_fee') and detail.percentage_fee != vals['percentage_fee']) or detail.price != vals['price'] or detail.price_ship !=
                    vals['price_ship']):
                vals['last_update_price_date'] = datetime.now().isoformat()
                model = detail.with_context(connector_no_export=True)
                model.write(vals)
                return True
        return False

    def run_first_offer(self, detail):
        prices = self.backend_adapter.get_lowest_price([detail.sku, detail.marketplace_id.id_mws]) if detail.sku else None
        return prices

    def run_get_price(self, binding):
        prices = self.backend_adapter.get_my_price([binding.sku, binding.marketplace_id.id_mws]) if binding.sku else None
        return prices


class ProductDataImporter(Component):
    """ Import data for a record.

        Usually called from importers, in ``_after_import``.
        For instance from the products importer.
    """

    _name = 'amazon.product.data.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.product.product']
    _usage = 'amazon.product.data.import'

    def run_products_for_id(self, ids, type_id, marketplace_mws):
        _logger.info('connector_amazon [%s][%s] log: Get products with ean to export these to Amazon' % (os.getpid(), inspect.stack()[0][3]))
        products = self.backend_adapter.get_products_for_id(arguments=[ids, marketplace_mws, type_id])
        return products
