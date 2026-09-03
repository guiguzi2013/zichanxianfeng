// 可尽调抵押物判定（2026-09-02 用户确认细化，与后端 extractor.is_valid_collateral 一致）
// 规则：抵押物必须是房产/不动产类（我们只对房产估价），且描述具体
//   （位置细节 或 面积 或 证号 或 门牌号模式，至少一项）。
// 不合格：纯类型词（如"住宅房产"）、非房产（设备/股权/车辆等）、
//   描述只有大范围（如"青岛市黄岛区"）无具体位置。
// 位置细节含：路/街/大道/巷/弄/小区/苑/花园/幢/栋/层/室/镇/村/县/乡/
//   高新区/保税区/开发区/金融区 等专有区域；普通"XX区/XX市"不算。

const REAL_ESTATE_TYPES = ['住宅', '商业', '工业', '土地', '厂房', '写字楼', '商铺', '公寓',
  '别墅', '仓储', '办公', '门店', '车位', '房产', '不动产', '楼', '大厦']
const PURE_TYPE_WORDS = ['房产', '住宅', '住宅房产', '商业', '商业用房', '工业', '工业厂房',
  '土地', '厂房', '写字楼', '商铺', '公寓', '别墅', '仓储', '办公',
  '门店', '车位', '抵押物', '不动产', '无', '—', '-', '其他']
const POSITION_DETAIL = ['路', '街', '大道', '巷', '弄', '小区', '苑', '花园', '幢', '栋',
  '层', '室', '镇', '村', '县', '乡',
  '高新区', '保税区', '开发区', '金融区']
const AREA_RE = /(㎡|平方米|平米|平方)/
const CERT_RE = /(权证|房产证|不动产权证|登记证明|产权证)/
const DOOR_NUM_RE = /\d+\s*(号|幢|栋|室|层|单元)/

export function hasValidCollateral(collateralDesc, collateralType) {
  const text = (collateralDesc || '').trim()
  const ctype = (collateralType || '').trim()
  if (!text) return false
  if (PURE_TYPE_WORDS.includes(text)) return false
  const combined = text + ctype
  // ① 必须是房产/不动产类
  if (!REAL_ESTATE_TYPES.some((k) => combined.includes(k))) return false
  // ② 描述必须具体：位置细节 / 面积 / 证号 / 门牌号，至少一项
  if (POSITION_DETAIL.some((k) => text.includes(k))) return true
  if (AREA_RE.test(text)) return true
  if (CERT_RE.test(text)) return true
  return DOOR_NUM_RE.test(text)
}

// 可尽调三要素判定：债务人 + 债权本金 + 抵押物合格
export function canDueDiligence(detail) {
  const d = detail || {}
  const debtor = (d.debtor_name || '').trim()
  const claim = (d.claim_total || '').trim()
  if (!debtor || !claim) return false
  return hasValidCollateral(d.collateral_desc, d.collateral_type)
}
