import { useEffect, useRef } from 'react'

/**
 * ECharts 封装（依赖 public/vendor/echarts.min.js 提供的全局 echarts）
 * 图表色板固定走设计令牌（见 global.css --chart-*）
 */
export default function MarketChart({ option, height = 220, style }) {
  const ref = useRef(null)
  const chartRef = useRef(null)

  useEffect(() => {
    if (!ref.current || !window.echarts) return
    chartRef.current = window.echarts.init(ref.current)
    const resize = () => chartRef.current?.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    if (chartRef.current && option) {
      chartRef.current.setOption(option, true)
    }
  }, [option])

  if (!window.echarts) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-weak)', fontSize: 13 }}>
        图表组件加载失败（需要网络访问 ECharts）
      </div>
    )
  }
  return <div ref={ref} style={{ width: '100%', height, ...style }} />
}
