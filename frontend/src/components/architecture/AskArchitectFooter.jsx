import { Link } from 'react-router-dom'
import { MessageSquare, ArrowRight } from 'lucide-react'

const AskArchitectFooter = () => (
  <div className="bg-blue-50 border border-blue-100 rounded-xl p-6 mt-8">
    <div className="flex items-start gap-4">
      <div className="w-10 h-10 rounded-lg bg-blue-100 flex items-center justify-center flex-shrink-0">
        <MessageSquare className="w-5 h-5 text-blue-600" />
      </div>
      <div className="flex-1">
        <h3 className="text-base font-semibold text-gray-900">Vraag advies aan de Architect</h3>
        <p className="text-sm text-gray-600 mt-1">
          Heb je specifieke vragen over de core, architectonische keuzes, of hoe componenten samenwerken?
          Start een gesprek en vraag advies aan de Architect agent.
        </p>
        <Link
          to="/chat"
          className="inline-flex items-center gap-1.5 mt-3 px-4 py-2 text-sm font-medium text-blue-700 bg-blue-100 hover:bg-blue-200 rounded-lg transition-colors"
        >
          Vraag advies
          <ArrowRight className="w-4 h-4" />
        </Link>
      </div>
    </div>
  </div>
)

export default AskArchitectFooter
