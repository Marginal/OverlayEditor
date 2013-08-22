// -*- mode: c -*-

#version 120

attribute float skip;	// would prefer bool, but that requires GLSL 1.30

void main()
{
    gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
    gl_Position.z += skip * 2 * gl_Position.w;	// send beyond far clipping plane
    gl_FrontColor = gl_BackColor = gl_Color;
    gl_TexCoord[0].st = vec2(gl_MultiTexCoord0.s, 1.0 - gl_MultiTexCoord0.t);	// Flip vertically
}
