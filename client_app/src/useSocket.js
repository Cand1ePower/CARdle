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
    frunk_open: false,
    trunk_open: false,
    seat_heat_fl: 0,
    seat_heat_fr: 0,
    seat_vent_fl: 0,
    seat_vent_fr: 0,
    ambient_color: '#000000',
    ambient_brightness: 50,
    ac_on: true
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
          // AC Fan Speed Handling
          if (intent === 'Set_Air_Condition_Wind') {
             const level = (slots && slots.Number) ? parseInt(slots.Number) : 3;
             setVehicleState(prev => ({...prev, ac_fan: level}));
          } else if (intent === 'Inc_Air_Condition_Wind') {
             const delta = (slots && slots.Number) ? parseInt(slots.Number) : 1;
             setVehicleState(prev => ({...prev, ac_fan: Math.min(5, prev.ac_fan + delta)}));
          } else if (intent === 'Dec_Air_Condition_Wind') {
             const delta = (slots && slots.Number) ? parseInt(slots.Number) : 1;
             setVehicleState(prev => ({...prev, ac_fan: Math.max(1, prev.ac_fan - delta)}));
          }
          if (intent === 'Close_Air_Condition' || intent === 'Close_AC') {
             setVehicleState(prev => ({...prev, ac_on: false}));
          }
          if (intent === 'Open_Air_Condition' || intent === 'Open_AC') {
             setVehicleState(prev => ({...prev, ac_on: true}));
          }
          // Ambient Light Handling
          if (intent === 'Open_Env_Light' || intent === 'Set_Env_Light_Color' || intent === 'Set_Env_Light_Theme') {
             const colorMap = { '红': '#ef4444', '蓝': '#3b82f6', '绿': '#10b981', '紫': '#a855f7', '黄': '#eab308', '白': '#ffffff', '粉': '#ec4899', '青': '#06b6d4', '橙': '#f97316' };
             let hexColor = '#3b82f6'; // default blue
             if (slots && slots.Color) {
                for (const [k, v] of Object.entries(colorMap)) {
                   if (slots.Color.includes(k)) { hexColor = v; break; }
                }
             }
             setVehicleState(prev => ({...prev, ambient_color: hexColor}));
          }
          if (intent === 'Close_Env_Light') {
             setVehicleState(prev => ({...prev, ambient_color: '#000000'}));
          }
          // Trunk & Frunk Handling
          if (intent === 'Open_Trunk') {
             if (frameContent && frameContent.includes('前盖')) {
                 setVehicleState(prev => ({...prev, frunk_open: true}));
             } else {
                 setVehicleState(prev => ({...prev, trunk_open: true}));
             }
          }
          if (intent === 'Close_Trunk') {
             if (frameContent && frameContent.includes('前盖')) {
                 setVehicleState(prev => ({...prev, frunk_open: false}));
             } else {
                 setVehicleState(prev => ({...prev, trunk_open: false}));
             }
          }
          if (intent === 'Open_Front_Trunk') {
             setVehicleState(prev => ({...prev, frunk_open: true}));
          }
          if (intent === 'Close_Front_Trunk') {
             setVehicleState(prev => ({...prev, frunk_open: false}));
          }
          // Seat Heating & Ventilation Handling
          if (intent === 'Open_Heated_Seat' || intent === 'Set_Seat_Temperature') {
             const level = slots && slots.Ratio === '小' ? 1 : (slots && slots.Ratio === '中' ? 2 : 3);
             setVehicleState(prev => ({...prev, seat_heat_fl: level, seat_heat_fr: level, seat_vent_fl: 0, seat_vent_fr: 0}));
          }
          if (intent === 'Close_Heated_Seat' || intent === 'Close_Heating') {
             setVehicleState(prev => ({...prev, seat_heat_fl: 0, seat_heat_fr: 0}));
          }
          if (intent === 'Open_Seat_Ventilation' || intent === 'Set_Seat_Ventilation') {
             const level = slots && slots.Ratio === '大' ? 3 : 2;
             setVehicleState(prev => ({...prev, seat_vent_fl: level, seat_vent_fr: level, seat_heat_fl: 0, seat_heat_fr: 0}));
          }
          if (intent === 'Close_Seat_Ventilation') {
             setVehicleState(prev => ({...prev, seat_vent_fl: 0, seat_vent_fr: 0}));
          }
          // Media & Nav (Unified Media Player)
          const playIntents = ['Children_Story_Play', 'Play_Music', 'View_Play_Music', 'Play_Local_Radio', 'Play_Online_Music', 'Play_Audiobook', 'Play_BT_Music', 'Play_USB_Music', 'Play_OL_Radio', 'Play_Hot_Radio', 'Open_Radio_By_Name', 'View_Play_Radio', 'View_Play_News', 'Search_Radio', 'Search_News'];
          if (playIntents.includes(intent)) {
             let name = slots?.Name || slots?.Singer || slots?.Station || slots?.Category || '推荐内容';
             setMediaState({ title: name, playing: true });
          }
          if (intent === 'Search_Music') {
             let songTitle = (slots?.Singer ? slots.Singer + ' - ' : '') + (slots?.Song || '未知歌曲');
             if (songTitle === '未知歌曲' && slots?.Singer) songTitle = slots.Singer + '的歌曲';
             setMediaState({ title: songTitle, playing: true });
          }
          if (intent === 'Media_Pause' || intent === 'Stop_Audio') {
             setMediaState(prev => ({...prev, playing: false}));
          }
          if (intent === 'Continue_Play' || intent === 'Play_Media_Collection' || intent === 'Replay') {
             setMediaState(prev => ({...prev, playing: true}));
          }
          if (intent === 'Media_Next' || intent === 'Media_Last') {
             setMediaState(prev => ({...prev, playing: true, title: '切换中...' }));
             setTimeout(() => {
                 setMediaState(prev => ({...prev, title: '随机播放推荐音乐'}));
             }, 1500);
          }
          if (intent === 'Navigation_Location_Query' || intent === 'Go_POI' || intent === 'Add_Via' || intent === 'Go_Home' || intent === 'Go_Company') {
             let dest = slots?.POI || slots?.Target || '未知目的地';
             if (intent === 'Go_Home') dest = '家';
             if (intent === 'Go_Company') dest = '公司';
             setNavState({ destination: dest });
          }
        }
        // Handle Errors
        else if (func === 'ERROR') {
          setNlgText(frameContent || '发生未知错误，请重试');
          setIsTyping(false);
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
