import GenericRequest from './GenericRequest.jsx'

export default function HTTPPanel({ providers }) {
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-7xl mx-auto px-4 md:px-6 py-4 md:py-6">
        <div className="mb-4 md:mb-6">
          <h1 className="text-lg md:text-xl font-semibold">HTTP / REST</h1>
          <p className="text-xs md:text-sm text-ink-400 mt-0.5 md:mt-1">Call any configured HTTP endpoint — preset, send, inspect.</p>
        </div>
        <GenericRequest providers={providers} />
      </div>
    </div>
  )
}
