// -*- mode: c -*-

#version 120

attribute vec4 transform;	// x,y,z,hdg
attribute float selected;	// would prefer bool, but that requires GLSL 1.30
varying vec2 texcoord;

void main()
{
    float coshdg = cos(transform.w);
    float sinhdg = sin(transform.w);
    mat4 t = mat4(coshdg, 0.0, sinhdg, 0.0,
                  0.0, 1.0, 0.0, 0.0,
                  -sinhdg, 0.0, coshdg, 0.0,
                  transform.x, transform.y, transform.z, 1.0); 
    gl_Position = gl_ProjectionMatrix * t * gl_Vertex;
    gl_FrontColor = gl_BackColor = vec4(1.0, selected * -0.5 + 1.0, 1.0, 1.0);
    texcoord = vec2(gl_MultiTexCoord0.s, 1.0 - gl_MultiTexCoord0.t);	// Flip vertically
}
