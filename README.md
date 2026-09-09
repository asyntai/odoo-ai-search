# Asyntai - AI Search for Odoo

Visitors know what they want but not what it is called. A normal search box matches words, so "something to carry my laptop in" finds nothing. Asyntai AI Search understands what they mean and shows the right products, pages and blog posts, with photo, price and availability right inside the search box.

This module puts the Asyntai AI Search Bar on your Odoo website. It reads your catalogue through your own Odoo, with the prices and stock your shop shows, and Asyntai reads your pages and blog posts. Nothing to paste, nothing to configure.

## What your visitors get

* Results that match what they mean, not only the exact words they type
* Product photo, price and availability inside the search box
* Answers about delivery, returns and opening hours, taken from your own pages
* The bar speaks the visitor's language

## What you get

* Fewer dead ends. Visitors reach the product or the page instead of leaving
* Prices and stock that come straight from your shop, pricelist and tax included
* No code to touch. The bar adds itself to your header, or replaces the search box you already show
* Free to start. If the monthly allowance runs out, Odoo's own search takes over until it resets

## Requirements

* Odoo 16, 17, 18 or 19, on Odoo.sh or your own server
* The Website app. With eCommerce installed, products are searched too
* Outgoing HTTPS from your server

## Installation

1. Copy the `asyntai_search` folder into your addons directory, or install it from the Odoo Apps Store
2. Restart Odoo, open Apps, and press Update Apps List
3. Search for Asyntai and install **Asyntai - AI Search**
4. Open **Asyntai AI Search** in the app switcher and press **Connect Asyntai**
5. Sign in, or create a free account. The bar switches on by itself when your site has been read

## Where the bar appears

One setting, **Where the bar goes**, with four answers:

* **Automatic.** Replaces the header search box if your site shows one, otherwise adds the bar to the header. Exactly one bar, never two
* **In place of the search box my site already shows**
* **Add the bar to the site header.** Works with every Odoo header layout, on desktop and in the mobile menu
* **Only where I add the block myself.** Drop an HTML block with `<div data-asyntai-search></div>` wherever the bar should go

## Documentation

[asyntai.com/documentation/odoo-ai-search/](https://asyntai.com/documentation/odoo-ai-search/)

## Have a question?

Email us at hello@asyntai.com or try our chatbot at [asyntai.com](https://asyntai.com/)
