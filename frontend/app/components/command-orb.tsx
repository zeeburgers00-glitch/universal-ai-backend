"use client";

import { Float, Sparkles } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { useRef } from "react";
import type { Group, Mesh } from "three";

function EnergyCore() {
  const group = useRef<Group>(null);
  const ring = useRef<Mesh>(null);

  useFrame((state, delta) => {
    if (group.current) {
      group.current.rotation.y += delta * 0.12;
      group.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.16) * 0.13;
    }
    if (ring.current) {
      ring.current.rotation.z -= delta * 0.09;
    }
  });

  return (
    <group ref={group}>
      <Float speed={1.4} rotationIntensity={0.16} floatIntensity={0.22}>
        <mesh>
          <icosahedronGeometry args={[1.15, 5]} />
          <meshPhysicalMaterial
            color="#59d9cb"
            emissive="#0c6965"
            emissiveIntensity={0.62}
            roughness={0.19}
            metalness={0.62}
            clearcoat={1}
            clearcoatRoughness={0.12}
          />
        </mesh>
        <mesh scale={1.38}>
          <icosahedronGeometry args={[1.15, 3]} />
          <meshBasicMaterial color="#8df8e9" wireframe transparent opacity={0.14} />
        </mesh>
      </Float>

      <mesh ref={ring} rotation={[1.08, 0.32, 0.18]}>
        <torusGeometry args={[1.76, 0.012, 12, 180]} />
        <meshBasicMaterial color="#6ee7d8" transparent opacity={0.62} />
      </mesh>
      <mesh rotation={[0.22, 0.8, -0.64]}>
        <torusGeometry args={[2.05, 0.006, 10, 180]} />
        <meshBasicMaterial color="#8ba9a0" transparent opacity={0.36} />
      </mesh>

      {[
        [1.84, 0.5, 0.35],
        [-1.55, 0.82, -0.5],
        [0.54, -1.75, 0.9],
        [-0.76, -1.44, -1.05],
        [1.18, -0.92, -0.9]
      ].map((position, index) => (
        <mesh key={index} position={position as [number, number, number]}>
          <sphereGeometry args={[0.055, 16, 16]} />
          <meshBasicMaterial color={index % 2 === 0 ? "#b6fff2" : "#d5ad7c"} />
        </mesh>
      ))}

      <Sparkles count={52} scale={5.6} size={2.0} speed={0.32} color="#a6eee1" />
    </group>
  );
}

export default function CommandOrb() {
  return (
    <div className="orb-canvas" aria-label="Animated 3D AI network core">
      <Canvas
        camera={{ position: [0, 0, 6.2], fov: 35 }}
        dpr={[1, 1.5]}
        gl={{ antialias: true, alpha: true, powerPreference: "low-power" }}
      >
        <ambientLight intensity={0.72} />
        <pointLight position={[3, 4, 4]} intensity={22} color="#8ff5e8" />
        <pointLight position={[-4, -2, 1]} intensity={11} color="#c58e5a" />
        <EnergyCore />
      </Canvas>
    </div>
  );
}
