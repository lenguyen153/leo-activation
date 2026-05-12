import { useState } from 'react';
import AppLayout from './components/layout/AppLayout';
import Header from './components/layout/Header';
import AgentPanel from './components/chatbot/AgentPanel';
import Audience360 from './pages/Audience360';
import CampaignEngine from './pages/CampaignEngine';

const TABS = [
  { id: 'audience', label: '👤 Audience 360' },
  { id: 'campaign', label: '🚀 Campaign Engine' },
];

export default function App() {
  const [view, setView] = useState('audience');

  return (
    <div className="app">
      <Header />
      <AppLayout
        tabs={TABS}
        activeTab={view}
        onTabChange={setView}
        agentPanel={<AgentPanel />}
      >
        {view === 'audience' ? <Audience360 /> : <CampaignEngine />}
      </AppLayout>
    </div>
  );
}
