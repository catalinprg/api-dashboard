import { useState } from 'react'
import LLMChat from './LLMChat.jsx'
import GenericRequest from './GenericRequest.jsx'
import ComparePanel from './ComparePanel.jsx'

export default function Playground({ providers }) {
  const [tab, setTab] = useState('llm')
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-7xl mx-auto px-4 md:px-6 py-4 md:py-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4 md:mb-6">
          <div>
            <h1 className="text-lg md:text-xl font-semibold">Playground</h1>
            <p className="text-xs md:text-sm text-ink-400 mt-0.5 md:mt-1">Test configured APIs — LLMs or any HTTP service.</p>
          </div>
          <div className="flex gap-1 p-1 bg-ink-900 border border-ink-700 rounded-lg self-start sm:self-auto overflow-x-auto">
            <TabBtn active={tab === 'llm'} onClick={() => setTab('llm')}>LLM chat</TabBtn>
            <TabBtn active={tab === 'compare'} onClick={() => setTab('compare')}>Compare</TabBtn>
            <TabBtn active={tab === 'http'} onClick={() => setTab('http')}>HTTP request</TabBtn>
          </div>
        </div>
        {tab === 'llm' && <LLMChat providers={providers} />}
        {tab === 'compare' && <ComparePanel providers={providers} />}
        {tab === 'http' && <GenericRequest providers={providers} />}
      </div>
    </div>
  )
}

function TabBtn({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-1.5 rounded-md text-sm font-medium transition ${
        active ? 'bg-accent text-white' : 'text-ink-400 hover:text-ink-100'
      }`}
    >
      {children}
    </button>
  )
}
