#!/usr/bin/env python3
"""Curate the live Droplinked OpenAPI into the developer-facing API reference.

Usage:
  python3 scripts/curate-openapi.py [raw_openapi.json]
If no path is given, fetches the live spec from apiv3dev.droplinked.com/api-doc-json.

Drops admin/internal operations, normalizes + orders tags into clean groups, and
writes api-reference/openapi.json (read by Mintlify). Re-run when the API changes.
The upstream fix is consistent @ApiTags in droplinked-backend; this keeps the
published reference clean until then.
"""
import json, sys, os, urllib.request

EXCLUDE = {
  'admin','admin-affiliate','shop-admin','Admin · Credit Events','admin-business-health',
  'http-req','ScannerDecoy','Crawler','Deployment Log','Swagger','rbac','DynamicRouter',
  'User Features','CredibleX','Analytics','POD Raw Products','App','storage',
}
RENAME = {
  'ShopV2':'Shops','shopV2-api-key':'Shops','Product V2':'Products','SKU-V2':'Products',
  'Collections-V2':'Collections','CartV2':'Cart','Order-v2':'Orders','Shipping-V2':'Shipping',
  'EasyPost Rates':'Shipping','customer-v2':'Customers','merchant-v2-auth':'Authentication',
  'address-book':'Address Book','subscription':'Subscriptions','AI':'AI Tools','NFTs':'NFTs',
  'Web3':'Web3','Blockchain':'Web3','Crypto Rails':'Web3','Affiliate V2':'Affiliate',
  'affiliate':'Affiliate','Affiliate Commission':'Affiliate','giftCard':'Gift Cards',
  'Credits':'Credits','Currency':'Currency','blogs':'Blogs','Social Media Quests':'Quests',
  'Gamification':'Quests','Widget':'Widgets','Uploader':'Media','locations':'Locations',
  'notifications':'Notifications','Webhook':'Webhooks','stripe':'Payments',
  'stripe-connect':'Payments','Paypal':'Payments','paypal':'Payments','paypal-connect':'Payments',
  'paymob-connect':'Payments','Bonum PSP':'Payments','Telr PSP':'Payments','payments':'Payments',
}
ORDER = [
 ('Authentication','Obtain and manage merchant/customer access tokens.'),
 ('Shops','Read and manage shops, storefront config, and API keys.'),
 ('Products','Products, SKUs, pricing, and the public catalog.'),
 ('Collections','Group products into collections.'),
 ('Cart','Build carts, attach customers, and prepare checkout.'),
 ('Orders','Create and track orders and fulfillment.'),
 ('Shipping','Shipping profiles, rates, and address-based estimates.'),
 ('Payments','Card (Stripe), PayPal, and regional PSP payment flows.'),
 ('Customers','Customer accounts and profiles.'),
 ('Address Book','Saved customer addresses.'),
 ('Subscriptions','Droplinked platform subscription billing.'),
 ('Gift Cards','Issue and redeem gift cards.'),
 ('Credits','Account credits and balances.'),
 ('Currency','Supported currencies and conversion.'),
 ('AI Tools','AI generation + moderation endpoints.'),
 ('Web3','On-chain commerce, blockchain, and crypto rails.'),
 ('NFTs','NFT minting and management.'),
 ('Affiliate','Affiliate network, links, and commissions.'),
 ('Blogs','Shop blog content.'),('Quests','Gamification and social quests.'),
 ('Widgets','Embeddable widgets.'),('Media','Image/file uploads.'),
 ('Locations','Countries, states, and cities reference data.'),
 ('Notifications','Notification endpoints.'),('Webhooks','Inbound webhook receivers.'),
]
SRC = sys.argv[1] if len(sys.argv) > 1 else None
if SRC:
    d = json.load(open(SRC))
else:
    with urllib.request.urlopen('https://apiv3dev.droplinked.com/api-doc-json', timeout=30) as r:
        d = json.loads(r.read())
ct = lambda t: RENAME.get(t, t)
paths, kept, dropped = {}, 0, 0
for p, v in d['paths'].items():
    newops = {}
    for m, op in v.items():
        if m not in ('get','post','put','patch','delete') or not isinstance(op, dict):
            newops[m] = op; continue
        keep = [ct(t) for t in op.get('tags', []) if t not in EXCLUDE]
        if not keep:
            dropped += 1; continue
        seen = set(); op['tags'] = [x for x in keep if not (x in seen or seen.add(x))]
        newops[m] = op; kept += 1
    if any(m in ('get','post','put','patch','delete') for m in newops):
        paths[p] = newops
d['paths'] = paths
present = {t for v in paths.values() for op in v.values() if isinstance(op, dict) for t in op.get('tags', [])}
d['servers'] = [{'url':'https://apiv3.droplinked.com','description':'Production'},
                {'url':'https://apiv3dev.droplinked.com','description':'Development'}]
d['tags'] = [{'name':n,'description':desc} for n,desc in ORDER if n in present] + \
            [{'name':t} for t in sorted(present) if t not in {n for n,_ in ORDER}]
out = os.path.join(os.path.dirname(__file__), '..', 'api-reference', 'openapi.json')
json.dump(d, open(out, 'w'), indent=0)
print(f'curated: kept {kept}, dropped {dropped}; {len(paths)} paths; {len(d["tags"])} groups')
