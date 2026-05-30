import { useState, useEffect, useCallback } from 'react';
import { io } from 'socket.io-client';

const SOCKET_SERVER_URL = 'http://127.0.0.1:8000';
const DEVICE_ID = 'CARDLE_DEV_001';

export function useSocket() {
  const [socket, setSocket] = useState(null);
  const [connected, setConnected] = useState(false);
  const [nlgText, setNlgText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  
  // App State Data
  const [vehicleState, setVehicleState] = useState({
    window_fl: 0, window_fr: 0, window_rl: 0, window_rr: 0,
    ac_temp: 24, ac_fan: 3,
    ambient_color: '#000000' // Base default
  });
  
  const [mediaState, setMediaState] = useState({
    title: '', playing: false
  });
  
  const [navState, setNavState] = useState({
    destination: ''
  });

  useEffect(() => {
    const newSocket = io(`${SOCKET_SERVER_URL}?device_id=${DEVICE_ID}`, {
      transports: ['websocket', 'polling']
    });

    newSocket.on('connect', () => {
      console.log('[Socket] Connected');
      setConnected(true);
    });

    newSocket.on('disconnect', () => {
      console.log('[Socket] Disconnected');
      setConnected(false);
    });

    newSocket.on('request_nlu', (dataStr) => {
      try {
        const frame = JSON.parse(dataStr);
        const { func, status, intent, slots, frame: frameContent, branch } = frame;
        
        console.log('[Socket] Received:', frame);

        // Handle Chat stream
        if (func === 'CHAT') {
          if (status === 0) {
            setIsTyping(true);
            setNlgText('');
          } else if (status === 1) {
            setNlgText(prev => prev + frameContent);
          } else if (status === 2) {
            setIsTyping(false);
          }
        } 
        // Handle Reject
        else if (func === 'REJECT') {
          setNlgText(frameContent);
          setIsTyping(false);
        }
        // Handle Skills (Vehicle, Media, Nav)
        else if (func === 'SKILL') {
          setNlgText(frameContent || `执行意图: ${intent}`);
          setIsTyping(false);
          
          // Apply State Changes based on intent
          if (intent === 'Open_Window' || intent === 'Close_Window') {
             const target = intent === 'Open_Window' ? 100 : 0;
             setVehicleState(prev => ({...prev, window_fl: target, window_fr: target, window_rl: target, window_rr: target}));
          }
          if (intent === 'Set_AC_Temperature') {
             if (slots && slots.Temperature) {
               setVehicleState(prev => ({...prev, ac_temp: parseInt(slots.Temperature) || prev.ac_temp}));
             }
          }
          if (intent === 'Children_Story_Play') {
             setMediaState({ title: slots?.Name || '故事', playing: true });
          }
          if (intent === 'Navigation_Location_Query') {
             setNavState({ destination: slots?.POI || '未知目的地' });
          }
        }
        
      } catch (e) {
        console.error('[Socket] Error parsing data:', e);
      }
    });

    setSocket(newSocket);
    return () => newSocket.close();
  }, []);

  const sendCommand = useCallback((query) => {
    if (!socket || !connected) return;
    
    setIsTyping(true);
    setNlgText('正在思考...');
    
    const payload = {
      query,
      trace_id: `tid_ui_${Date.now()}`,
      last_answer: ''
    };
    
    socket.emit('request_nlu', JSON.stringify(payload));
  }, [socket, connected]);

  return { connected, sendCommand, nlgText, isTyping, vehicleState, mediaState, navState };
}
