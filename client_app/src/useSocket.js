import { useState, useEffect, useCallback } from 'react';
import { io } from 'socket.io-client';
import { v4 as uuidv4 } from 'uuid';

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
    trunk_open: false, frunk_open: false,
    seat_heat_fl: 0, seat_heat_fr: 0,
    seat_vent_fl: 0, seat_vent_fr: 0,
    ambient_color: '#000000'
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
             if (slots && (slots.Position === '主驾' || slots.Position === '左前')) {
                setVehicleState(prev => ({...prev, window_fl: target}));
             } else if (slots && (slots.Position === '副驾' || slots.Position === '右前')) {
                setVehicleState(prev => ({...prev, window_fr: target}));
             } else if (slots && (slots.Position === '左后')) {
                setVehicleState(prev => ({...prev, window_rl: target}));
             } else if (slots && (slots.Position === '右后')) {
                setVehicleState(prev => ({...prev, window_rr: target}));
             } else {
                // 如果没指定位置，全开/全关
                setVehicleState(prev => ({...prev, window_fl: target, window_fr: target, window_rl: target, window_rr: target}));
             }
          }
          if (intent === 'Set_AC_Temperature' || intent === 'Set_Air_Condition_Temperature') {
             const temp = (slots && slots.Number) ? slots.Number : (slots && slots.Temperature);
             if (temp) {
               setVehicleState(prev => ({...prev, ac_temp: parseInt(temp) || prev.ac_temp}));
             }
          } else if (intent === 'Inc_Air_Condition_Temperature') {
             const delta = (slots && slots.Number) ? parseInt(slots.Number) : null;
             setVehicleState(prev => {
                let current = prev.ac_temp;
                let target = delta ? (delta < 10 ? current + delta : delta) : current + 2;
                return {...prev, ac_temp: Math.min(32, target)};
             });
          } else if (intent === 'Dec_Air_Condition_Temperature') {
             const delta = (slots && slots.Number) ? parseInt(slots.Number) : null;
             setVehicleState(prev => {
                let current = prev.ac_temp;
                let target = delta ? (delta < 10 ? current - delta : delta) : current - 2;
                return {...prev, ac_temp: Math.max(16, target)};
             });
          }
          // Trunk & Frunk Handling
          if (intent === 'Open_Trunk') {
             setVehicleState(prev => ({...prev, trunk_open: true}));
          }
          if (intent === 'Close_Trunk') {
             setVehicleState(prev => ({...prev, trunk_open: false}));
          }
          if (intent === 'Open_Front_Trunk') {
             setVehicleState(prev => ({...prev, frunk_open: true}));
          }
          if (intent === 'Close_Front_Trunk') {
             setVehicleState(prev => ({...prev, frunk_open: false}));
          }
          // Seat Heating & Ventilation Handling
          if (intent === 'Open_Seat_Heating' || intent === 'Set_Seat_Temperature') {
             const level = slots && slots.Ratio === '小' ? 1 : (slots && slots.Ratio === '中' ? 2 : 3);
             setVehicleState(prev => ({...prev, seat_heat_fl: level, seat_heat_fr: level, seat_vent_fl: 0, seat_vent_fr: 0}));
          }
          if (intent === 'Close_Seat_Heating' || intent === 'Close_Heating') {
             setVehicleState(prev => ({...prev, seat_heat_fl: 0, seat_heat_fr: 0}));
          }
          if (intent === 'Open_Seat_Ventilation' || intent === 'Set_Seat_Ventilation') {
             const level = slots && slots.Ratio === '大' ? 3 : 2;
             setVehicleState(prev => ({...prev, seat_vent_fl: level, seat_vent_fr: level, seat_heat_fl: 0, seat_heat_fr: 0}));
          }
          if (intent === 'Close_Seat_Ventilation') {
             setVehicleState(prev => ({...prev, seat_vent_fl: 0, seat_vent_fr: 0}));
          }
          // Media & Nav
          if (intent === 'Children_Story_Play' || intent === 'Play_Music' || intent === 'View_Play_Music') {
             setMediaState({ title: slots?.Name || '流行音乐', playing: true });
          }
          if (intent === 'Navigation_Location_Query' || intent === 'Go_POI') {
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
      trace_id: uuidv4().replace(/-/g, ''), // Generate a 32-char hex string
      last_answer: ''
    };
    
    socket.emit('request_nlu', JSON.stringify(payload));
  }, [socket, connected]);

  return { connected, sendCommand, nlgText, isTyping, vehicleState, mediaState, navState };
}
