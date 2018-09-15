# -*- coding: utf-8 -*-
# Copyright 2017 Halltic eSolutions S.L. ()
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name':'Amazon Connector',
    'version':'0.1.0',
    'author':'Halltic eSolutions S.L.',
    'maintainer':'True',
    'website':'False',
    'license':'',

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/master/openerp/addons/base/module/module_data.xml # noqa
    # for the full list
    'category':'Connector', 'summary':'It is a connector to MWS Amazon account',
    'description':"""
.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

==============
Amazon conector
==============

This module extends the functionality of Sales module

Be carefull, this module install a harmfull utility to your e-commerce strategy. If you sell on this marketplace, you are given your data to your competition (Amazon) and they will use your products with their minimun and maximun prices to know how, when and how much to sell cheaper than you. Even more, you send to they your suppliers data and they can negotiate with this to get better prices than you if they need. Amazon do not play clean and is bread for today and hungry for tomorrow

This module is a connector for Amazon. With this can connect your odoo instance with the Amazon account.
Sell in Amazon has some dangers that you must be consider:
* Amazon will have your suppliers because in a lot of cases you will need send to they the invoices to justify that the products are originals or 
others behaivours. In this moment Amazon will know who is the supplier/s of the products that you sell.
* Amazon could sell the same product that you. Remember that from the first moment they know where go to buy this.
* Amazon could block your product to sell if you have a lot of sales of this (Remember that in this moment Amazon will are sell the same product that you)

Installation
============

To install this module, you need to:

#. Do this ...

Configuration
=============

To configure this module, you need to:

#. Go to Connector-->Amazon-->Account
#. Add account's credentials. When the account is created the inventory will be imported
#. The module is start up to import orders from Amazon

.. figure:: path/to/local/image.png
   :alt: alternative description
   :width: 600 px

Usage
=====

To use this module, you need to:

#. Go to ...

.. image:: https://odoo-community.org/website/image/ir.attachment/5784_f2813bd/datas
   :alt: Try me on Runbot
   :target: https://runbot.odoo-community.org/runbot/{repo_id}/{branch}


Known issues / Roadmap
======================

* Add ...

Bug Tracker
===========

Bugs are tracked on `GitHub Issues
<https://github.com/OCA/{project_repo}/issues>`_. In case of trouble, please
check there if your issue has already been reported. If you spotted it first,
help us smashing it by providing a detailed and welcomed feedback.

Credits
=======

Images
------

* Odoo Community Association: `Icon <https://github.com/OCA/maintainer-tools/blob/master/template/module/static/description/icon.svg>`_.

Contributors
------------

* Tristán Mozos <tristan.mozos@halltic.com>

Funders
-------

The development of this module has been financially supported by:

* Halltic eSolutions S.L.

Maintainer
----------

.. image:: https://odoo-community.org/logo.png
   :alt: Odoo Community Association
   :target: https://odoo-community.org

This module is maintained by the Halltic eSolutions S.L.

To contribute to this module, please visit https://github.com/TristanMozos/



""",

    # any module necessary for this one to work correctly
    'depends':['connector',
               'base_technical_user',
               'sale_stock',
               'product_margin',
               'delivery',
               'product_brand',
               'product_dimension',
               'partner_address_street3',
               'connector_ecommerce'],

    # always loaded
    'data':[
        # 'security/ir.model.access.csv',
        'wizards/wizard_import_orders.xml',
        'views/amazon_config_views.xml',
        'views/amazon_backend_views.xml',
        'views/amazon_order_views.xml',
        'views/amazon_partner_views.xml',
        'views/amazon_product_views.xml',
        'views/amazon_return_views.xml',
        'views/connector_amazon_menu.xml',
        'data/amazon_connector_data.xml',
        'data/amazon_connector_config_settings.xml',
        'data/quota_mws_data.xml',
        # 'data/amazon.config.product.category.csv',
    ],
    # only loaded in demonstration mode
    'demo':[
        'demo/demo.xml'
    ],

    'js':[],
    'css':[],
    'qweb':[],

    'installable':True,
    # Install this module automatically if all dependency have been previously
    # and independently installed.  Used for synergetic or glue modules.
    'auto_install':False,
    'application':True,
}
