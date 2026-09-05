import { useNavigate } from 'react-router-dom'

/** 智收云风格四栏页脚：关于平台 / 联系我们 / 快捷导航 / 声明 */
export default function AppFooter() {
  const navigate = useNavigate()

  const go = (path) => () => navigate(path)

  return (
    <footer className="app-footer">
      <div className="footer-inner">
        <div className="footer-col">
          <div className="footer-col-title">关于平台</div>
          <a onClick={go('/')}>平台介绍</a>
          <a onClick={go('/upload')}>智能尽调</a>
          <a onClick={go('/property-clues')}>财产线索</a>
          <a onClick={go('/debtor-profile')}>债务人画像</a>
          <a onClick={go('/valuation')}>土地厂房估价</a>
          <a>用户协议</a>
          <a>隐私政策</a>
          <a>意见反馈</a>
        </div>
        <div className="footer-col">
          <div className="footer-col-title">联系我们</div>
          <p>服务热线：400-000-0000</p>
          <p>客户服务：service@nplcn.cn</p>
          <p>商务合作：biz@nplcn.cn</p>
          <p>工作时间：工作日 9:00-18:00</p>
        </div>
        <div className="footer-col">
          <div className="footer-col-title">快捷导航</div>
          <a onClick={go('/')}>债权公告</a>
          <a onClick={go('/upload')}>智能尽调</a>
          <a onClick={go('/debtor-profile')}>债务人画像</a>
          <a onClick={go('/valuation')}>土地厂房估价</a>
          <a onClick={go('/tasks')}>我的任务</a>
          <a onClick={go('/admin')}>管理后台</a>
        </div>
        <div className="footer-col">
          <div className="footer-col-title">免责声明</div>
          <p style={{ lineHeight: 1.7 }}>
            本平台为信息聚合与尽调分析工具，所有报告由系统基于公开信息和 系统分析自动生成，仅供参考，不构成投资建议。
          </p>
        </div>
      </div>
      <div className="footer-bottom">
        数据来源：公开渠道（司法公开 / 信用公示 / 拍卖平台）
        <br />
        Copyright ©2025-2026 NPL CN 版权所有 ｜ 中国不良资产 · 尽调与投融资
      </div>
    </footer>
  )
}
