// 验证 shortCityName 逻辑(独立复现)
const shortCityName = (s) => {
  if (!s) return ''
  const t = String(s).trim()
  const cities = t.match(/([\u4e00-\u9fa5]{2,4})市/g)
  if (cities && cities.length) return cities[cities.length - 1].replace('市', '')
  const p = t.match(/(?:省|自治区|特别行政区)\s*([\u4e00-\u9fa5]{2,6})/)
  if (p) return p[1]
  return t.length > 5 ? t.slice(0, 5) : t
}
const cases = ['衡阳市','开封市','昆明市','青岛市黄岛区','青岛市胶州市水岸府邸东区小区','临夏市','兰州市','债权转让','破产捡漏','内蒙古自治区呼和浩特市','']
for (const c of cases) console.log(`${c || '(空)'} → ${shortCityName(c) || '(空)'}`)
