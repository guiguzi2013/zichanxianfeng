/**
 * 首页市场三栏图表演示数据（债权转让/抵押资产/破产专区）
 * 说明：宏观数据条 / KPI / 拍卖平台 / AMC 排行已接入 /api/home/dashboard（真实数据，后台可维护）；
 * 本文件的「三栏行情图表」仍需真实行情数据源（如对接拍卖平台 API / 银登中心），当前为演示数据并已在页面上标注。
 */
export const marketDemo = {
  // 宏观数据条
  macro: [
    { label: '不良贷款余额', value: '3.7', unit: '万亿' },
    { label: '商业银行不良率', value: '1.51', unit: '%' },
    { label: '持牌 AMC 数量', value: '64', unit: '家' },
    { label: '年处置规模', value: '3.8', unit: '万亿' },
  ],
  // 三栏市场
  columns: [
    {
      key: 'transfer',
      title: '债权转让',
      stats: [
        { label: '信用债', value: '3,800', unit: '亿' },
        { label: '抵押债', value: '1,571', unit: '亿' },
        { label: '总户数', value: '35,181', unit: '户' },
      ],
      subtitle: '近一年累计债转 5,371.92 亿元',
      chart: buildChart([['25-09', 420], ['25-10', 388], ['25-11', 451], ['25-12', 402], ['26-01', 467], ['26-02', 396], ['26-03', 438], ['26-04', 472], ['26-05', 505], ['26-06', 487]]),
      rankTitle: '活跃受让机构',
      rank: [
        { name: '中信金融资产管理', pct: 19.33 },
        { name: '信达资产管理', pct: 16.34 },
        { name: '东方资产管理', pct: 13.99 },
      ],
    },
    {
      key: 'collateral',
      title: '抵押资产',
      stats: [
        { label: '信用债', value: '4,687', unit: '亿' },
        { label: '抵押债', value: '1,811', unit: '亿' },
        { label: '总户数', value: '31,602', unit: '户' },
      ],
      subtitle: '近一年累计债转 6,499.15 亿元',
      chart: buildChart([['25-09', 366], ['25-10', 341], ['25-11', 398], ['25-12', 355], ['26-01', 410], ['26-02', 352], ['26-03', 389], ['26-04', 425], ['26-05', 447], ['26-06', 431]]),
      rankTitle: '活跃受让机构',
      rank: [
        { name: '河南国锦管理合伙', pct: 13.04 },
        { name: '天津弘发企业管理', pct: 12.83 },
        { name: '浙商资产管理', pct: 6.2 },
      ],
    },
    {
      key: 'bankruptcy',
      title: '破产专区',
      stats: [
        { label: '信用债', value: '1.27', unit: '万亿' },
        { label: '抵押债', value: '3.24', unit: '万亿' },
        { label: '总户数', value: '40,307', unit: '户' },
      ],
      subtitle: '近一年 AMC 处置招商 4.52 万亿元',
      chart: buildChart([['25-09', 512], ['25-10', 478], ['25-11', 540], ['25-12', 495], ['26-01', 566], ['26-02', 508], ['26-03', 552], ['26-04', 588], ['26-05', 612], ['26-06', 593]]),
      rankTitle: '活跃 AMC',
      rank: [
        { name: '中信金融资产管理', pct: 32.71 },
        { name: '信达资产管理', pct: 22.84 },
        { name: '长城资产管理', pct: 17.35 },
      ],
    },
  ],
}

// 柱状(信用债蓝/抵押债灰) + 折线(红) 组合图表
function buildChart(pairs) {
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['信用债', '抵押债', '全部'], top: 0, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11 } },
    grid: { left: 8, right: 8, top: 28, bottom: 4, containLabel: true },
    xAxis: {
      type: 'category',
      data: pairs.map((p) => p[0]),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#E5E9F0' } },
      axisLabel: { fontSize: 10, color: '#8A94A6' },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#EEF1F6' } },
      axisLabel: { fontSize: 10, color: '#8A94A6' },
    },
    series: [
      {
        name: '信用债',
        type: 'bar',
        barWidth: 8,
        data: pairs.map((p, i) => Math.round(p[1] * (0.72 + 0.04 * i))),
        itemStyle: { color: '#2F6BFF', borderRadius: [2, 2, 0, 0] },
      },
      {
        name: '抵押债',
        type: 'bar',
        barWidth: 8,
        data: pairs.map((p) => Math.round(p[1] * 0.45)),
        itemStyle: { color: '#9CA3AF', borderRadius: [2, 2, 0, 0] },
      },
      {
        name: '全部',
        type: 'line',
        smooth: true,
        symbolSize: 4,
        data: pairs.map((p) => p[1]),
        lineStyle: { color: '#E6453F', width: 2 },
        itemStyle: { color: '#E6453F' },
      },
    ],
  }
}
