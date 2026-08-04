export type OrderState='awaiting_payment'|'candidate_seen'|'finality_pending'|'authority_pending'|'key_ready';
export type OfflineOrder={id:string; state:OrderState; activationKey?:string};
export const offlineOrders:Record<string,OfflineOrder>={
 'demo-awaiting':{id:'demo-awaiting',state:'awaiting_payment'}, 'demo-candidate':{id:'demo-candidate',state:'candidate_seen'}, 'demo-finality':{id:'demo-finality',state:'finality_pending'}, 'demo-authority':{id:'demo-authority',state:'authority_pending'}, 'demo-ready':{id:'demo-ready',state:'key_ready',activationKey:'GM1.TEST-ONLY-NONPRODUCTION-EXAMPLE'}
};
export const orderStateLabels:Record<OrderState,string>={awaiting_payment:'等待付款',candidate_seen:'已看到候選付款',finality_pending:'等待鏈上最終確認',authority_pending:'等待授權 Authority 確認',key_ready:'授權碼已準備'};
