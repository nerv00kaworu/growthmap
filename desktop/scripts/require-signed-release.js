'use strict';
if(process.env.GROWTHMAP_COMMERCIAL_RELEASE!=='1'||!process.env.WIN_CSC_LINK||!process.env.WIN_CSC_KEY_PASSWORD){console.error('Signed commercial release requires GROWTHMAP_COMMERCIAL_RELEASE=1, WIN_CSC_LINK, and WIN_CSC_KEY_PASSWORD');process.exit(1);}
