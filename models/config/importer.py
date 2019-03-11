# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# © 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
import urllib2
import base64
from datetime import datetime

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
        return {'name':record['name'] if len(record['name']) < 159 else record['name'][:160]}

    @mapping
    def backend_id(self, record):
        return {'backend_id':self.backend_record.id}

    @mapping
    def odoo_id(self, record):
        if record.get('odoo_id'):
            return {'odoo_id':record['odoo_id']}
        return None

    @mapping
    def barcode(self, record):
        if record.get('odoo_id'):
            odoo_prod = self.env['product.product'].browse(record['odoo_id'])
            if odoo_prod.barcode or odoo_prod.product_tmpl_id.barcode:
                return {'barcode':odoo_prod.barcode or odoo_prod.product_tmpl_id.barcode}
            elif record.get('id_product'):
                return {'barcode':record['id_product']}
        return None


class ProductImporter(Component):
    _name = 'amazon.product.product.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.product.product']

    def _get_amazon_data(self):
        """ Return the raw Amazon data for ``self.external_id`` """
        if self.amazon_record:
            return self.amazon_record
        product = {'sku':self.external_id}
        default_market = self.backend_record._get_marketplace_default()
        product['marketplace_id'] = default_market.id

        rce = self.env['res.currency']

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

        # If there is a product that match default_code with sku and barcode we will link the product of odoo with new amazon product
        products = self.env['product.product'].search([('default_code', '=like', self.amazon_record['sku'])]) or \
                   self.env['product.template'].search([('default_code', '=like', self.amazon_record['sku'])]).mapped('product_variant_id')

        prod_aux = None

        for market in self.backend_record.marketplace_ids:
            # We are going to search products with the same amazon.sku and odoo.default_code and the same barcode
            if products and not prod_aux:
                for prod in products:
                    if prod.barcode or prod.product_tmpl_id.barcode:
                        test = self.backend_adapter.get_products_for_id(arguments=[[prod.barcode or prod.product_tmpl_id.barcode],
                                                                                   market.id_mws,
                                                                                   None])
                        if test:
                            prod_aux = prod
                            break
                # Assign the odoo search product to relation (amazon - odoo) product
                if prod_aux:
                    self.amazon_record['odoo_id'] = prod_aux.id

    def _get_binary_image(self, image_url):
        url = image_url.encode('utf8')
        try:
            request = urllib2.Request(url)
            binary = urllib2.urlopen(request)
        except urllib2.HTTPError as err:
            if err.code == 404:
                # the image is just missing, we skip it
                return
            else:
                # we don't know why we couldn't download the image
                # so we propagate the error, the import will fail
                # and we have to check why it couldn't be accessed
                raise
        else:
            return binary.read()

    def _write_brand(self, binding, product_data):
        if product_data.get('brand'):
            brand = self.env['product.brand'].search([('name', '=', product_data['brand'])])
            if not brand:
                result = self.env['product.brand'].create({'name':product_data['brand']})
                product_data['product_brand_id'] = result.id
            else:
                product_data['product_brand_id'] = brand[0].id

            # TODO At sign up several products on the same time, we can create the same brand several times. We need solve this error
            binding.product_tmpl_id.write({'product_brand_id':product_data.get('product_brand_id')})
            binding.write({'brand':product_data['brand']})
        else:
            _logger.error("Creating brand product for sku (%s) data (%s)", binding.sku, product_data)

    def _write_dimensions(self, binding, product_data):

        ept = self.env['product.template']
        ppt = ept.pool.get('product.template')
        epu = self.env['amazon.product.uom']

        if product_data.get('height'):
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

        if product_data.get('length'):
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

        if product_data.get('width'):
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

        if product_data.get('weight'):
            try:
                if isinstance(product_data['weight'], dict):
                    amaz_w_units = product_data['weight'].getvalue('Units').lower()
                    weight_units = epu.search([('name', '=', amaz_w_units)])
                    if weight_units and weight_units.product_uom_id.uom_type != 'reference':
                        weight_reference = self.env['product.uom'].search(
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
        self.external_id = binding.external_id
        data_product = self.backend_adapter.read(external_id=self.external_id, attributes=marketplace.id_mws)
        self._write_brand(binding, data_product)
        self._write_dimensions(binding, data_product)
        if data_product.get('url_images'):
            images = data_product['url_images']
            while images:
                image_url = images.pop()
                binary = self._get_binary_image(image_url)
                self._write_image_data(binding, binary)

        return data_product

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
        data['type'] = 'product'
        binding = super(ProductImporter, self)._create(data)
        return binding

    def _is_uptodate(self, binding):
        if binding:
            return True

    def _after_import(self, binding):
        """ Hook called at the end of the import """
        if self.amazon_record and self.amazon_record.get('marketplace_id'):
            self._write_product_data(binding, self.amazon_record.get('marketplace'))
            importer = self.component(usage='amazon.assign.product.listprice')
            for sub_binding in binding.product_product_market_ids:
                importer.run(sub_binding)
                importer = self.component(usage='amazon.product.category')
                importer.run(sub_binding)

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

    direct = [('sku', 'sku'),
              ('title', 'title'),
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
    def names(self, record):
        if record.get('sku') and record.get('marketplace_id'):
            return {'name':record['sku'] + ' || ' + self.env['amazon.config.marketplace'].browse(record['marketplace_id']).name}
        return

    @mapping
    def website_id(self, record):
        return {'website_id':None}

    @mapping
    def item_ids(self, record):
        pricelist = self.env['product.pricelist'].search([('sku', '=', record['sku']), ('marketplace_price_id', '=', record['marketplace_id'])])

        now_time = datetime.now()
        item = []
        prc_items = [prc_item for prclst in pricelist if pricelist for prc_item in prclst.item_ids if not prc_item.date_end]
        for p in prc_items:
            item.append([1,
                         p.id,
                         {'date_end':now_time.isoformat(), }])

        # The product type 'product' is the product to sell
        item.append([0,
                     0,
                     {'applied_on':'1_product',
                      'compute_price':'fixed',
                      'min_quantity':1,
                      'date_start':now_time.isoformat(),
                      'fixed_price':record.get('price_unit'), }])
        item.append([0,
                     0,
                     {'applied_on':'1_product',
                      'compute_price':'fixed',
                      'min_quantity':1,
                      'date_start':now_time.isoformat(),
                      'fixed_price':record.get('price_shipping'), }])

        return {'item_ids':item}

    @mapping
    def marketplace_id(self, record):
        return {'marketplace_id':record.get('marketplace_id')}

    @mapping
    def marketplace_price_id(self, record):
        '''
        Return the marketplace to product_pricelist
        :param record:
        :return:
        '''
        return {'marketplace_price_id':record.get('marketplace_id')}

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
    def external_id(self, record):
        return {'external_id':record['sku'] + '|-|' + str(self.env['amazon.config.marketplace'].browse(record['marketplace_id']).id)}


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


class ProductCategoryImporter(Component):
    _name = 'amazon.product.category.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.product.product']
    _usage = 'amazon.product.category'

    def _update_category(self, product_detail, product_data):
        eacpc = self.env['amazon.config.product.category']

        category = None
        if product_data:
            category_name = product_data.get('category_name') or product_data.get('productgroup')
            category = eacpc.search([('name', '=', category_name)])

        detail_market = self.env['amazon.product.product.detail'].search(
            [('product_id.sku', '=', product_detail.sku), ('marketplace_id', '=', product_detail.marketplace_id)])
        if detail_market:
            detail_market.write({'category_id':category.id if category else eacpc.search([('name', '=', 'default')]).id,
                                 'category_searched':True if category else False})

    def run(self, record):
        import wdb
        wdb.set_trace()
        if record.marketplace_id:
            try:
                data = self.backend_adapter.get_category([record.sku, record.marketplace_id.id_mws])
            except Exception as e:
                data = None
            self._update_category(record, data)


class ProductLowestPriceImporter(Component):
    """ Import data for a record.

        Usually called from importers, in ``_after_import``.
        For instance from the products importer.
    """

    _name = 'amazon.product.lowestprice.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.product.product']
    _usage = 'amazon.product.lowestprice'

    def _insert_first_price(self, record, data):
        lowest_price = float('inf')
        for offer in data:
            vals = {'product_detail_id':record.id,
                    'id_seller':self.backend_record.seller if offer['my_offer'] == 'true' else '',
                    'price':offer['price'],
                    'currency_price_id':self.env['res.currency'].search([('name', '=', offer['currency_price'])]),
                    'price_ship':offer['ship_price'] if offer.get('ship_price') else 0,
                    'currency_price_id':self.env['res.currency'].search([('name', '=', offer['ship_currency'])]),
                    'is_buybox':offer['buybox_winner'] == 'true',
                    'seller_feedback':offer['feedback_rating'],
                    'amazon_fulffilled':offer['amazon_fulfilled'] == 'true'}

            if offer['my_offer'] == 'true':
                record.has_buybox = vals['is_buybox']
                record.first_price_searched = True

            if vals['price'] + vals['price_ship'] < lowest_price:
                lowest_price = vals['price'] + vals['price_ship']

            result = self.env['amazon.product.offer'].create(vals)

        if record.lowest_price != lowest_price:
            record.lowest_price = lowest_price

    def run(self, record):
        '''
        This method is called for get the lowest price, buybox, etc and the category of the product on the marketplace
        We get the data and we update only the data of the marketplace selected
        :param binding:
        :return:
        '''
        try:
            import wdb
            wdb.set_trace()
            if record.marketplace_id and not record.first_price_searched:
                data = self.backend_adapter.get_lowest_price([record.sku, record.marketplace_id.id_mws])
                self._insert_first_price(record, data)
        except Exception as e:
            _logger.error(e.message)


class ProductAssignPricelistImporter(Component):
    '''
    Importer to recover the price product and price ship and write it on pricelist
    '''
    _name = 'amazon.assign.product.pricelist.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.product.product']
    _usage = 'amazon.assign.product.listprice'

    def _assign_product_pricelist(self, binding):
        com_ship = self.component(usage='order.line.builder.shipping')
        ship_service = com_ship.env.ref('.'.join(com_ship.product_ref))
        product_id_done = False
        for item in binding.odoo_id.item_ids:
            if not item.date_end:
                if not product_id_done and binding.price == item.fixed_price:
                    item.write({'product_tmpl_id':binding.product_id.odoo_id.product_tmpl_id.id})
                    product_id_done = True
                elif binding.price_ship == item.fixed_price:
                    item.write({'product_tmpl_id':ship_service.product_tmpl_id.id})

    def run(self, binding):
        if binding and binding.odoo_id:
            self._assign_product_pricelist(binding)


class ProductPriceImporter(Component):
    """ Import data for a record.

        Usually called from importers, in ``_after_import``.
        For instance from the products importer.
    """

    _name = 'amazon.product.price.importer'
    _inherit = 'amazon.importer'
    _apply_on = ['amazon.product.product']
    _usage = 'amazon.product.price.import'

    def run(self, binding):
        prices = self.backend_adapter.get_my_price([binding.sku, binding.marketplace_id.id_mws])
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
        products = self.backend_adapter.get_products_for_id(arguments=[ids, marketplace_mws, type_id])
        return products
