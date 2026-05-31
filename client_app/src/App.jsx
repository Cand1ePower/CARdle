import React, { useState, useEffect } from 'react';
import { Mic, Navigation2, Music, Car, Settings, Disc, MapPin, Thermometer, Wind, Wifi, WifiOff } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useSocket } from './useSocket';
import './index.css';

function App() {
  const { connected, sendCommand, nlgText, isTyping, vehicleState, mediaState, navState } = useSocket();
  const [inputText, setInputText] = useState('');
  
  // Barge-in Demo States
  const [foldProgress, setFoldProgress] = useState(0); // 0 = upright, 100 = folded flat
  const [isFolding, setIsFolding] = useState(0); // 1 = folding, -1 = unfolding, 0 = stopped

  useEffect(() => {
    let timer;
    if (isFolding !== 0) {
      timer = setInterval(() => {
        setFoldProgress(prev => {
          const next = prev + (isFolding * 1.5); // 1.5% per tick for smooth slow fold
          if (next >= 100) { setIsFolding(0); return 100; }
          if (next <= 0) { setIsFolding(0); return 0; }
          return next;
        });
      }, 50);
    }
    return () => clearInterval(timer);
  }, [isFolding]);
  
  // Voice Simulation with Frontend Intercept (Barge-in)
  const handleSimulateVoice = (e) => {
    e.preventDefault();
    if (inputText.trim()) {
      const lowerText = inputText.trim();
      
      // Barge-in Check: If we say "停止" while folding is in progress, interrupt immediately
      if ((lowerText.includes('停') || lowerText.includes('断')) && isFolding !== 0) {
        setIsFolding(0);
        // We still send the command to the backend to log it, but UI reacts at 0 latency
      } else if (lowerText.includes('开始折叠') || lowerText.includes('折叠座椅')) {
        setIsFolding(1);
      } else if (lowerText.includes('展开') || lowerText.includes('复位')) {
        setIsFolding(-1);
      }
      
      sendCommand(inputText);
      setInputText('');
    }
  };

  return (
    <div 
      className="app-container" 
      style={{ 
        background: `radial-gradient(circle at 50% 30%, ${vehicleState.ambient_color === '#000000' ? 'transparent' : vehicleState.ambient_color + '40'} 0%, var(--bg-dark) 80%)`,
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
            <h1 className="text-gradient" style={{ fontSize: '1.8rem', margin: 0, letterSpacing: '1px' }}>CARdle OS <span style={{fontSize:'1rem', color:'var(--text-muted)'}}>PRO</span></h1>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'var(--bg-panel)', padding: '0.35rem 1rem', borderRadius: '100px', fontSize: '0.85rem', border: '1px solid var(--glass-border)' }}>
               {connected ? <Wifi size={14} color="var(--accent-cyan)" /> : <WifiOff size={14} color="#ef4444" />}
               {connected ? <span style={{color: 'var(--text-secondary)'}}>Gateway Synced</span> : <span style={{color: '#ef4444'}}>Offline</span>}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '2rem', alignItems: 'center', fontWeight: 600, fontSize: '1.3rem' }}>
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
               <div style={{ width: '180px', height: '380px', background: 'rgba(255,255,255,0.02)', border: '2px solid var(--glass-border)', borderRadius: '60px', position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', boxShadow: 'inset 0 0 40px rgba(0,0,0,0.5)' }}>
                  
                  {/* Frunk (Front Trunk) Warning Overlay */}
                  <AnimatePresence>
                    {vehicleState.frunk_open && (
                      <motion.div 
                        initial={{ opacity: 0, scale: 0.8 }}
                        animate={{ opacity: 1, scale: 1, y: -10 }}
                        exit={{ opacity: 0, scale: 0.8 }}
                        style={{ position: 'absolute', top: '-40px', left: '-20px', right: '-20px', background: 'rgba(239, 68, 68, 0.9)', color: 'white', padding: '8px', borderRadius: '8px', textAlign: 'center', fontWeight: 'bold', zIndex: 10, boxShadow: '0 4px 20px rgba(239,68,68,0.6)' }}
                      >
                         ⚠️ WARNING: FRUNK OPEN
                      </motion.div>
                    )}
                  </AnimatePresence>

                  <motion.div 
                    animate={{ y: vehicleState.frunk_open ? -30 : 0, opacity: vehicleState.frunk_open ? 0.8 : 0.2 }}
                    style={{ position: 'absolute', top: '10px', width: '120px', height: '50px', background: vehicleState.frunk_open ? 'rgba(239,68,68,0.2)' : 'rgba(255,255,255,0.1)', borderRadius: '20px 20px 5px 5px', border: `1px solid ${vehicleState.frunk_open ? '#ef4444' : 'var(--glass-border)'}`, display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1 }}
                  >
                     <span style={{ fontSize: '0.7rem', color: vehicleState.frunk_open ? '#fca5a5' : 'var(--text-muted)' }}>{vehicleState.frunk_open ? 'FRUNK OPEN' : ''}</span>
                  </motion.div>

                  {/* Windows Visualization */}
                  <WindowIndicator position="top: 120px; left: -6px;" open={vehicleState.window_fl > 0} />
                  <WindowIndicator position="top: 120px; right: -6px;" open={vehicleState.window_fr > 0} />
                  <WindowIndicator position="bottom: 120px; left: -6px;" open={vehicleState.window_rl > 0} />
                  <WindowIndicator position="bottom: 120px; right: -6px;" open={vehicleState.window_rr > 0} />
                  
                  {/* Seats Area */}
                  <div style={{ position: 'absolute', top: '130px', width: '100%', display: 'flex', justifyContent: 'center', gap: '20px' }}>
                     {/* Front Left Seat */}
                     <div className={`seat-heat-${vehicleState.seat_heat_fl} seat-vent-${vehicleState.seat_vent_fl}`} style={{ width: '45px', height: '60px', borderRadius: '10px 10px 5px 5px', border: '1px solid var(--glass-border)', transition: 'all 0.5s', position: 'relative', background: vehicleState.seat_heat_fl > 0 ? 'rgba(234, 88, 12, 0.4)' : undefined }}>
                        <div style={{ position: 'absolute', top: '-15px', left: '10px', width: '25px', height: '12px', borderRadius: '4px', background: vehicleState.seat_heat_fl > 0 ? '#ea580c' : 'rgba(255,255,255,0.1)', border: '1px solid var(--glass-border)', boxShadow: vehicleState.seat_heat_fl > 0 ? '0 0 10px #ea580c' : 'none' }} />
                     </div>
                     {/* Front Right Seat */}
                     <div className={`seat-heat-${vehicleState.seat_heat_fr} seat-vent-${vehicleState.seat_vent_fr}`} style={{ width: '45px', height: '60px', borderRadius: '10px 10px 5px 5px', border: '1px solid var(--glass-border)', transition: 'all 0.5s', position: 'relative', background: vehicleState.seat_heat_fr > 0 ? 'rgba(234, 88, 12, 0.4)' : undefined }}>
                        <div style={{ position: 'absolute', top: '-15px', left: '10px', width: '25px', height: '12px', borderRadius: '4px', background: vehicleState.seat_heat_fr > 0 ? '#ea580c' : 'rgba(255,255,255,0.1)', border: '1px solid var(--glass-border)', boxShadow: vehicleState.seat_heat_fr > 0 ? '0 0 10px #ea580c' : 'none' }} />
                     </div>
                  </div>

                  {/* Barge-in Demo: Foldable Rear Seat */}
                  <div style={{ position: 'absolute', top: '220px', width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                     <div style={{ fontSize: '0.6rem', color: isFolding !== 0 ? 'var(--accent-cyan)' : 'var(--text-muted)', marginBottom: '8px', fontWeight: 600 }}>
                        {isFolding === 1 ? '正在折叠... (可打断)' : (isFolding === -1 ? '正在展开... (可打断)' : '后排座椅')}
                     </div>
                     <div style={{ display: 'flex', alignItems: 'flex-end', height: '40px', gap: '2px' }}>
                        {/* Seat Base */}
                        <div style={{ width: '45px', height: '12px', background: 'rgba(255,255,255,0.15)', borderRadius: '4px', border: '1px solid var(--glass-border)' }} />
                        {/* Seat Back (Folds down over the base) */}
                        <motion.div 
                           style={{ width: '12px', height: '40px', background: isFolding !== 0 ? 'var(--accent-cyan)' : 'rgba(255,255,255,0.3)', borderRadius: '4px', transformOrigin: 'bottom left', border: '1px solid var(--glass-border)', boxShadow: isFolding !== 0 ? '0 0 10px var(--accent-cyan)' : 'none' }}
                           animate={{ rotate: -(foldProgress * 0.9) }} // Folds leftwards over the base (0 to -90 deg)
                           transition={{ type: "tween", duration: 0.05 }}
                        />
                     </div>
                  </div>

                  {/* Trunk (Rear Trunk) */}
                  <motion.div 
                    animate={{ y: vehicleState.trunk_open ? 20 : 0, opacity: vehicleState.trunk_open ? 0.8 : 0.2 }}
                    style={{ position: 'absolute', bottom: '10px', width: '120px', height: '60px', background: 'rgba(255,255,255,0.1)', borderRadius: '5px 5px 20px 20px', border: '1px solid var(--glass-border)', display: 'flex', justifyContent: 'center', alignItems: 'center' }}
                  >
                     <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{vehicleState.trunk_open ? 'TRUNK OPEN' : ''}</span>
                  </motion.div>

               </div>
            </div>

            {/* AC Status overlay */}
            <div style={{ position: 'absolute', bottom: '2rem', right: '2rem', display: 'flex', gap: '1rem', opacity: vehicleState.ac_on ? 1 : 0.4, filter: vehicleState.ac_on ? 'none' : 'grayscale(100%)', transition: 'all 0.5s' }}>
               <div className="glass-panel flex-center" style={{ width: '64px', height: '64px', flexDirection: 'column', gap: '4px', background: vehicleState.ac_temp < 22 ? 'rgba(0,224,255,0.1)' : 'rgba(239,68,68,0.1)' }}>
                  <Thermometer size={20} color={vehicleState.ac_temp < 22 ? "var(--accent-cyan)" : "#ef4444"}/>
                  <span style={{ fontSize: '0.9rem', fontWeight: 600 }}>{vehicleState.ac_temp}°</span>
               </div>
               <div className="glass-panel flex-center" style={{ width: '64px', height: '64px', flexDirection: 'column', gap: '4px' }}>
                  <Wind size={20} color="var(--accent-cyan)" className="fan-blade" style={{ animation: vehicleState.ac_on ? `fan-spin ${2 / (vehicleState.ac_fan || 1)}s infinite linear` : 'none' }}/>
                  <span style={{ fontSize: '0.9rem', fontWeight: 600 }}>{vehicleState.ac_on ? `Lv.${vehicleState.ac_fan}` : 'OFF'}</span>
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
            <div className="glass-panel" style={{ padding: '2rem', flex: 1, display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' }}>
               {/* Ambient Glow */}
               <div style={{ position: 'absolute', top: -50, right: -50, width: '150px', height: '150px', background: 'var(--accent-purple)', filter: 'blur(80px)', opacity: mediaState.playing ? 0.5 : 0.1, transition: 'opacity 1s' }} />
               
               <h3 style={{ fontSize: '1.1rem', color: 'var(--text-secondary)', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem', zIndex: 1 }}>
                 <Music size={18} /> Media Player
               </h3>
               
               <div className="flex-center" style={{ gap: '2rem', marginTop: 'auto', marginBottom: 'auto', zIndex: 1, paddingLeft: '1rem' }}>
                  <motion.div 
                    animate={{ rotate: mediaState.playing ? 360 : 0 }}
                    transition={{ repeat: Infinity, duration: 8, ease: "linear" }}
                    style={{ 
                       width: '90px', height: '90px', 
                       background: 'linear-gradient(135deg, var(--accent-cyan), var(--accent-purple))', 
                       borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', 
                       boxShadow: mediaState.playing ? '0 0 30px rgba(139, 92, 246, 0.5)' : 'none' 
                    }}
                  >
                    <div style={{ width: '25px', height: '25px', background: 'var(--bg-dark)', borderRadius: '50%', border: '2px solid rgba(255,255,255,0.2)' }} />
                  </motion.div>
                  
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 700, fontSize: '1.4rem', marginBottom: '8px', letterSpacing: '0.5px' }}>{mediaState.title || 'Not Playing'}</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', height: '20px' }}>
                       <div style={{ fontSize: '0.95rem', color: mediaState.playing ? 'var(--accent-cyan)' : 'var(--text-muted)', fontWeight: 600 }}>
                          {mediaState.playing ? 'NOW PLAYING' : 'PAUSED'}
                       </div>
                       {mediaState.playing && (
                         <div style={{ display: 'flex', gap: '3px', height: '16px', alignItems: 'flex-end', marginLeft: '10px' }}>
                           <div className="eq-bar" /><div className="eq-bar" /><div className="eq-bar" /><div className="eq-bar" /><div className="eq-bar" />
                         </div>
                       )}
                    </div>
                  </div>
               </div>
            </div>

          </div>
        </div>

        {/* Bottom Voice Bar / Chat Log */}
        <div className="glass-panel" style={{ padding: '1.25rem 2rem', borderRadius: '100px', display: 'flex', alignItems: 'center', gap: '2rem', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
          
          <div 
             className={`flex-center ${isTyping ? 'voice-orb-active' : ''}`}
             style={{ 
               width: '64px', height: '64px', borderRadius: '50%', 
               background: 'linear-gradient(135deg, var(--accent-cyan), var(--accent-blue))', 
               flexShrink: 0,
               transition: 'all 0.3s ease'
             }}
          >
             <Mic size={28} color="white" />
          </div>
          
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
             <AnimatePresence mode="wait">
               <motion.div 
                 key={nlgText}
                 initial={{ opacity: 0, y: 15 }}
                 animate={{ opacity: 1, y: 0 }}
                 exit={{ opacity: 0, y: -15 }}
                 style={{ fontSize: '1.25rem', color: 'var(--text-primary)', lineHeight: 1.6, fontWeight: 500 }}
               >
                 {nlgText || '你好，我是舱舱。你可以尝试在右侧输入框向我发送指令...'}
               </motion.div>
             </AnimatePresence>
          </div>
          
          <form onSubmit={handleSimulateVoice} style={{ display: 'flex', gap: '0.75rem' }}>
             <input 
               type="text" 
               value={inputText}
               onChange={e => setInputText(e.target.value)}
               placeholder="输入语音指令..."
               style={{ 
                 background: 'rgba(0,0,0,0.5)', border: '1px solid var(--glass-border)', borderRadius: '100px', 
                 padding: '0.85rem 1.75rem', color: 'white', width: '280px', outline: 'none', fontSize: '1rem',
                 backdropFilter: 'blur(10px)'
               }}
             />
             <button type="submit" style={{ 
               background: 'var(--accent-blue)', color: 'white', border: 'none', borderRadius: '100px', padding: '0.85rem 2rem', cursor: 'pointer', fontWeight: 600, fontSize: '1rem',
               boxShadow: '0 4px 15px rgba(37, 99, 235, 0.4)'
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
