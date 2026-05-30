import React, { useState, useEffect } from 'react';
import { Mic, Navigation2, Music, Car, Settings, Disc, MapPin, Thermometer, Wind, Wifi, WifiOff } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useSocket } from './useSocket';
import './index.css';

function App() {
  const { connected, sendCommand, nlgText, isTyping, vehicleState, mediaState, navState } = useSocket();
  const [inputText, setInputText] = useState('');
  
  // Voice Simulation (since native Web Speech API requires HTTPS or localhost, we use a simple input for testing, but style it like voice)
  const handleSimulateVoice = (e) => {
    e.preventDefault();
    if (inputText.trim()) {
      sendCommand(inputText);
      setInputText('');
    }
  };

  return (
    <div 
      className="app-container" 
      style={{ 
        background: `radial-gradient(circle at top right, ${vehicleState.ambient_color} 0%, var(--bg-dark) 80%)`,
        height: '100vh', width: '100vw', display: 'flex', color: 'white',
        transition: 'background 2s ease-in-out'
      }}
    >
      {/* Sidebar Navigation */}
      <nav style={{
        width: '80px', borderRight: '1px solid var(--glass-border)', display: 'flex', flexDirection: 'column',
        alignItems: 'center', padding: '2rem 0', gap: '2rem', background: 'rgba(0,0,0,0.3)', backdropFilter: 'blur(10px)'
      }}>
        <div className="flex-center" style={{ width: '48px', height: '48px', borderRadius: '50%', background: 'var(--accent-blue)', marginBottom: 'auto' }}>
          <Car size={24} color="white" />
        </div>
        <NavItem icon={<Navigation2 />} active />
        <NavItem icon={<Music />} />
        <NavItem icon={<Settings />} />
      </nav>

      {/* Main Content Area */}
      <main style={{ flex: 1, padding: '2rem', display: 'flex', flexDirection: 'column', gap: '2rem', position: 'relative' }}>
        
        {/* Top Header */}
        <header className="flex-between">
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <h1 className="text-gradient" style={{ fontSize: '1.75rem', margin: 0 }}>CARdle OS</h1>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'var(--bg-panel)', padding: '0.25rem 0.75rem', borderRadius: '100px', fontSize: '0.85rem' }}>
               {connected ? <Wifi size={14} color="#10b981" /> : <WifiOff size={14} color="#ef4444" />}
               {connected ? 'Gateway Connected' : 'Offline'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'center', fontWeight: 600, fontSize: '1.2rem' }}>
            <span style={{ color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
               <Thermometer size={20} color="var(--accent-cyan)" /> {vehicleState.ac_temp}°C
            </span>
            <span style={{ color: 'var(--text-primary)' }}>16:42</span>
          </div>
        </header>

        {/* Dashboard Grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '2rem', flex: 1 }}>
          
          {/* Left: Car Sandbox */}
          <div className="glass-panel" style={{ padding: '2rem', display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' }}>
            <h2 style={{ fontSize: '1.25rem', marginBottom: '1rem', color: 'var(--text-secondary)' }}>Vehicle Overview</h2>
            
            <div className="flex-center" style={{ flex: 1, position: 'relative' }}>
               {/* Minimalist Car Top-Down View */}
               <div style={{ width: '160px', height: '340px', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--glass-border)', borderRadius: '40px', position: 'relative', display: 'flex', justifyContent: 'center' }}>
                  {/* Windows Visualization */}
                  <WindowIndicator position="top: 80px; left: -5px;" open={vehicleState.window_fl > 0} />
                  <WindowIndicator position="top: 80px; right: -5px;" open={vehicleState.window_fr > 0} />
                  <WindowIndicator position="bottom: 100px; left: -5px;" open={vehicleState.window_rl > 0} />
                  <WindowIndicator position="bottom: 100px; right: -5px;" open={vehicleState.window_rr > 0} />
                  <div style={{ position: 'absolute', top: '20px', color: 'var(--text-muted)' }}>Front</div>
               </div>
            </div>

            {/* AC Status overlay */}
            <div style={{ position: 'absolute', bottom: '2rem', right: '2rem', display: 'flex', gap: '1rem' }}>
               <div className="glass-panel flex-center" style={{ width: '60px', height: '60px', flexDirection: 'column', gap: '4px' }}>
                  <Thermometer size={20} color="var(--accent-cyan)"/>
                  <span style={{ fontSize: '0.9rem', fontWeight: 600 }}>{vehicleState.ac_temp}°</span>
               </div>
               <div className="glass-panel flex-center" style={{ width: '60px', height: '60px', flexDirection: 'column', gap: '4px' }}>
                  <Wind size={20} color="var(--accent-cyan)"/>
                  <span style={{ fontSize: '0.9rem', fontWeight: 600 }}>Lv.{vehicleState.ac_fan}</span>
               </div>
            </div>
          </div>

          {/* Right: Widgets */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
            
            {/* Nav Widget */}
            <div className="glass-panel" style={{ padding: '1.5rem', flex: 1, display: 'flex', flexDirection: 'column' }}>
               <h3 style={{ fontSize: '1rem', color: 'var(--text-secondary)', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                 <Navigation2 size={16} /> Navigation
               </h3>
               <div style={{ background: 'rgba(16, 185, 129, 0.1)', flex: 1, borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', border: '1px solid rgba(16, 185, 129, 0.2)' }}>
                  <MapPin size={32} color="#10b981" />
                  <div style={{ fontWeight: 600, fontSize: '1.1rem', color: '#10b981' }}>
                    {navState.destination ? navState.destination : '未设置目的地'}
                  </div>
               </div>
            </div>
            
            {/* Media Widget */}
            <div className="glass-panel" style={{ padding: '1.5rem', flex: 1, display: 'flex', flexDirection: 'column' }}>
               <h3 style={{ fontSize: '1rem', color: 'var(--text-secondary)', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                 <Music size={16} /> Media Player
               </h3>
               <div className="flex-center" style={{ gap: '1.5rem', marginTop: 'auto', marginBottom: 'auto' }}>
                  <motion.div 
                    animate={{ rotate: mediaState.playing ? 360 : 0 }}
                    transition={{ repeat: Infinity, duration: 4, ease: "linear" }}
                    style={{ width: '80px', height: '80px', background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 20px rgba(59, 130, 246, 0.4)' }}
                  >
                    <Disc size={32} color="white" />
                  </motion.div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: '1.2rem', marginBottom: '4px' }}>{mediaState.title || 'Not Playing'}</div>
                    <div style={{ fontSize: '0.9rem', color: 'var(--accent-blue)' }}>{mediaState.playing ? '▶ Playing...' : '-'}</div>
                  </div>
               </div>
            </div>

          </div>
        </div>

        {/* Bottom Voice Bar / Chat Log */}
        <div className="glass-panel" style={{ padding: '1.25rem 2rem', borderRadius: '100px', display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
          
          <motion.div 
             animate={{ scale: isTyping ? [1, 1.1, 1] : 1, boxShadow: isTyping ? '0 0 30px rgba(6, 182, 212, 0.6)' : '0 0 0px transparent' }}
             transition={{ repeat: isTyping ? Infinity : 0, duration: 1.5 }}
             className="flex-center" 
             style={{ 
               width: '56px', height: '56px', borderRadius: '50%', background: 'linear-gradient(135deg, #06b6d4, #3b82f6)', flexShrink: 0 
             }}
          >
             <Mic size={24} color="white" />
          </motion.div>
          
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
             <AnimatePresence mode="wait">
               <motion.div 
                 key={nlgText}
                 initial={{ opacity: 0, y: 10 }}
                 animate={{ opacity: 1, y: 0 }}
                 exit={{ opacity: 0, y: -10 }}
                 style={{ fontSize: '1.15rem', color: 'var(--text-primary)', lineHeight: 1.5 }}
               >
                 {nlgText || '你好，我是舱舱。你可以尝试在右侧输入框向我发送指令...'}
               </motion.div>
             </AnimatePresence>
          </div>
          
          <form onSubmit={handleSimulateVoice} style={{ display: 'flex', gap: '0.5rem' }}>
             <input 
               type="text" 
               value={inputText}
               onChange={e => setInputText(e.target.value)}
               placeholder="模拟语音输入..."
               style={{ 
                 background: 'rgba(0,0,0,0.4)', border: '1px solid var(--glass-border)', borderRadius: '100px', 
                 padding: '0.75rem 1.5rem', color: 'white', width: '250px', outline: 'none'
               }}
             />
             <button type="submit" style={{ 
               background: 'var(--accent-blue)', color: 'white', border: 'none', borderRadius: '100px', padding: '0.75rem 1.5rem', cursor: 'pointer', fontWeight: 600
             }}>发送</button>
          </form>
          
        </div>
      </main>
    </div>
  );
}

function NavItem({ icon, active }) {
  return (
    <div className="flex-center" style={{
      width: '48px', height: '48px', borderRadius: 'var(--radius-md)', background: active ? 'rgba(255,255,255,0.1)' : 'transparent',
      color: active ? 'white' : 'var(--text-muted)', cursor: 'pointer', transition: 'all 0.2s'
    }}>
      {icon}
    </div>
  )
}

function WindowIndicator({ position, open }) {
  return (
    <div style={{ 
      position: 'absolute', width: '4px', height: '40px', background: open ? 'var(--accent-cyan)' : 'var(--glass-border)', 
      borderRadius: '2px', transition: 'all 0.5s', boxShadow: open ? '0 0 10px var(--accent-cyan)' : 'none',
      ...position.split(';').reduce((acc, rule) => {
         const [k, v] = rule.split(':').map(s => s.trim());
         if(k && v) acc[k] = v;
         return acc;
      }, {})
    }} />
  )
}

export default App;
