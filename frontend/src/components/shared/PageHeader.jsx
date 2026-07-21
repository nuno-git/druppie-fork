const PageHeader = ({ title, subtitle, children }) => (
  <div className="flex items-center justify-between">
    <div className="min-w-0">
      <h1 className="text-xl font-bold text-gray-900 tracking-tight">{title}</h1>
      {subtitle && <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>}
    </div>
    {children && <div className="flex items-center gap-3 flex-shrink-0">{children}</div>}
  </div>
)

export default PageHeader
