// 企业名称输入校验(财产线索/债务人画像共用, 与 backend services/company_name_check.py 同步)
// 规则(2026-09-06 用户拍板): 仅支持企业; 自然人/疑似简称(名称不全)→ 即时提示填工商全称

const ORG_WORDS = ['公司', '集团', '有限', '股份', '控股', '合伙', '厂', '中心', '银行', '支行',
  '分行', '学校', '医院', '事务所', '合作社', '研究院', '工作室', '店', '社', '协会', '基金会',
  '驿站', '超市', '商场', '俱乐部', '园', '部', '所']

export function looksPerson(name) {
  const t = (name || '').trim()
  if (t.length < 2 || t.length > 60) return true
  if (ORG_WORDS.some((w) => t.includes(w))) return false
  return /^[\u4e00-\u9fa5]{2,4}$/.test(t)
}

export function looksAbbrev(name) {
  const t = (name || '').trim()
  if (looksPerson(t)) return false
  if (t.length < 2 || t.length > 60) return false
  // 不含任何企业主体词(且非短人名)→ 疑似字号/简称/不完整全称
  return !ORG_WORDS.some((w) => t.includes(w))
}
