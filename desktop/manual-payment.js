'use strict';
const MANUAL_PAYMENT=Object.freeze({mode:'manual',issuer:'Growthmap',baseNetwork:'eip155:8453',baseUsdc:'0x833589fCD6eDb6E08f4C7C32D4f71b54bdA02913',basePayee:'0x81d30e175a22c1c2f78b3db6fc0600a6e1cb3591',earlyLimit:50,earlyPriceMicros:10000000,regularPriceMicros:29000000,paypalUrl:'https://www.paypal.com/ncp/payment/R2M3YAQJNNCZA',supportEmail:'nerv00kaworu@gmail.com',supportXUrl:'https://x.com/nerv00kaworu'});
function validateManualPayment(value){
 if(!value||value.mode!=='manual'||value.issuer!=='Growthmap'||value.baseNetwork!=='eip155:8453'||value.baseUsdc!==MANUAL_PAYMENT.baseUsdc||!/^0x[0-9a-fA-F]{40}$/.test(value.basePayee)||value.earlyLimit!==50||value.earlyPriceMicros!==10000000||value.regularPriceMicros!==29000000||!/^https:\/\/(?:www\.)?paypal\.com\//i.test(value.paypalUrl)||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.supportEmail)||!/^https:\/\/x\.com\/[A-Za-z0-9_]+\/?$/.test(value.supportXUrl))throw new Error('Manual payment configuration is invalid');
 return Object.freeze({...value});
}
function publicManualPayment(){return validateManualPayment(MANUAL_PAYMENT);}
module.exports={publicManualPayment,validateManualPayment,MANUAL_PAYMENT};
