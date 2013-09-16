// -*- mode: c -*-

#version 120

attribute mat4 transform;
attribute float selected;	// would prefer bool, but that requires GLSL 1.30
varying vec2 texcoord;

void main()
{
    gl_Position = gl_ProjectionMatrix * transform * gl_Vertex;
    gl_FrontColor = gl_BackColor = vec4(1.0, selected * -0.5 + 1.0, 1.0, 1.0);
    texcoord = vec2(gl_MultiTexCoord0.s, 1.0 - gl_MultiTexCoord0.t);	// Flip vertically
}
